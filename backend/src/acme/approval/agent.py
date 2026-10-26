"""`run_approval(state)`: floor first, LLM second, clamp last (F15, design D7).

1. `apply_policy` sets the floor.
2. The approval LLM drafts a `Decision`.
3. Under VP scrutiny only, the Critic checks the draft; Approval revises up to
   `critic_max_rounds` times. A draft the Critic never passes ends as NEEDS_REVIEW.
4. final = stricter(floor, draft, critic suggestion): the LLM can tighten, never loosen.

Approval only produces a `Decision`; it never moves money.
"""

import json
from pathlib import Path

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from acme.approval import offline
from acme.approval.policy import STRICTNESS, PolicyResult, apply_policy, stricter
from acme.llm import active_models, get_chat_model
from acme.logging import agent_context, audit, dumps, run_context
from acme.models import Critique, Decision, InvoiceState, Outcome
from acme.settings import get_settings
from acme.validation.agent import untrusted

AGENT = "approval"
APPROVAL_PROMPT, CRITIC_PROMPT = "approval_v1", "critic_v1"
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_USER_SPLIT = "\n---- user ----\n"
AUTO = "Auto (rules)"

offline.register_offline()


def block(name: str, value) -> str:
    return f"<{name}>\n{dumps(value)}\n</{name}>"


def _render(prompt: str, **parts: str) -> list[BaseMessage]:
    system, user = (PROMPTS_DIR / f"{prompt}.md").read_text(encoding="utf-8").split(_USER_SPLIT, 1)
    for name, text in parts.items():
        user = user.replace("{{" + name + "}}", text)
    return [SystemMessage(system), HumanMessage(user)]


def _policy_block(policy: PolicyResult) -> str:
    return block("policy", {"floor": policy.floor, "rules": list(policy.rules), "fraud": policy.fraud,
                            "vp_scrutiny": policy.vp_scrutiny})


def _common(state: InvoiceState) -> dict[str, str]:
    invoice = state.invoice.model_dump_json(indent=2, exclude_none=True) if state.invoice else "(no invoice)"
    findings = [f.model_dump(mode="json", include={"code", "severity", "message", "evidence", "source"})
                for f in state.findings]
    return {"invoice": untrusted(invoice), "findings": block("findings", findings)}


def _draft(state: InvoiceState, policy: PolicyResult, previous: Decision | None,
           critique: Critique | None) -> Decision:
    revision = "" if critique is None else (
        "\n" + block("previous_draft", previous) + "\n\n" + block("critique", critique) + "\n")
    messages = _render(APPROVAL_PROMPT, **_common(state), revision=revision, policy=_policy_block(policy))
    model = get_chat_model("approval").with_structured_output(Decision)
    result = model.invoke(messages, config={"metadata": {"prompt_version": APPROVAL_PROMPT}})
    return result if isinstance(result, Decision) else Decision.model_validate(result)


def _critique(state: InvoiceState, policy: PolicyResult, draft: Decision) -> Critique:
    messages = _render(CRITIC_PROMPT, **_common(state), draft=block("draft", draft), policy=_policy_block(policy))
    model = get_chat_model("critic").with_structured_output(Critique)
    result = model.invoke(messages, config={"metadata": {"prompt_version": CRITIC_PROMPT}})
    return result if isinstance(result, Critique) else Critique.model_validate(result)


def _trace(state: InvoiceState, event: str, payload: dict) -> None:
    state.trace.append(json.loads(dumps({"agent": AGENT, "event": event, **payload})))
    audit(state.run_id, AGENT, event, payload)


def run_approval(state: InvoiceState) -> InvoiceState:
    """Decide `state` from its invoice, findings, and revision context; returns a new state."""
    state = state.model_copy(deep=True)
    models = active_models()
    vp, critic = models["approval"], models["critic"]
    with run_context(state.run_id), agent_context(AGENT):
        policy = apply_policy(state.invoice, state.findings, state.revision_context)
        _trace(state, "approval.policy", {"floor": policy.floor, "rules": list(policy.rules),
                                          "fraud": policy.fraud, "vp_scrutiny": policy.vp_scrutiny})
        draft = _draft(state, policy, None, None)
        _trace(state, "approval.draft", {"round": 0, "draft": draft, **vp})
        critique, critic_failed = None, False
        if policy.vp_scrutiny:
            max_rounds = get_settings().critic_max_rounds
            for round_no in range(max_rounds + 1):
                critique = _critique(state, policy, draft)
                _trace(state, "approval.critique", {"round": round_no, "critique": critique, **critic})
                if critique.passes:
                    break
                if round_no == max_rounds:
                    critic_failed = True
                    break
                draft = _draft(state, policy, draft, critique)
                _trace(state, "approval.draft", {"round": round_no + 1, "draft": draft, **vp})

        suggested = critique.suggested_outcome if critique else None
        final = stricter(policy.floor, draft.outcome, suggested, Outcome.NEEDS_REVIEW if critic_failed else None)
        notes = []
        if critic_failed:
            notes.append(f"Critic did not pass after {get_settings().critic_max_rounds} revisions: "
                         + "; ".join(critique.issues))
        for source, outcome in (("draft", draft.outcome), ("critic", suggested)):
            if outcome is not None and STRICTNESS[outcome] < STRICTNESS[final]:
                _trace(state, "approval.clamped", {"source": source, "proposed": outcome, "final": final,
                                                   "floor": policy.floor})
        if draft.outcome != final:
            notes.append(f"Draft outcome {draft.outcome} changed to {final} (tighten-only policy).")
        if final == Outcome.NEEDS_REVIEW:
            notes.append(f"AI recommendation: {draft.outcome}.")
        ai_decided = policy.vp_scrutiny or final != policy.floor
        decision = Decision(
            outcome=final,
            rationale=" ".join([draft.rationale.strip(), *notes]).strip(),
            rules_applied=list(policy.rules),
            confidence=draft.confidence,
            decided_by=f"AI VP ({vp['provider']}/{vp['model']})" if ai_decided else AUTO,
        )
        state.decision_draft, state.critique, state.decision = draft, critique, decision
        _trace(state, "approval.decision", {"decision": decision, "floor": policy.floor})
    return state
