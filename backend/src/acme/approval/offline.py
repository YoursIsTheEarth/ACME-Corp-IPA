"""Offline (`RuleBasedLLM`) behavior for Approval and the Critic (design D8).

- Approval: a template rationale built from the fired rules and findings; outcome = floor.
- Critic: passes when the draft is at least the floor and its rationale names every fired rule.

Both read the JSON blocks (`<policy>`, `<findings>`, `<draft>`) the agent puts in the prompt.
"""

import json
import re

from langchain_core.messages import BaseMessage

from acme.approval.policy import STRICTNESS
from acme.llm import register_handler
from acme.models import Critique, Decision, Outcome


def read_block(messages: list[BaseMessage], name: str):
    """The JSON in the last `<name>...</name>` block of the last message (the policy block comes last)."""
    content = str(messages[-1].content)
    matches = re.findall(rf"<{name}>\n(.*?)\n</{name}>", content, re.DOTALL)
    return json.loads(matches[-1]) if matches else None


def approval_draft(messages: list[BaseMessage]) -> Decision:
    policy = read_block(messages, "policy")
    findings = read_block(messages, "findings") or []
    floor, rules = Outcome(policy["floor"]), policy["rules"]
    fired = ", ".join(rules)
    if floor == Outcome.REJECT:
        details = "; ".join(f"{f['code']}: {f['message']}" for f in findings if f["severity"] == "CRITICAL")
        rationale = f"Rejected ({fired}). {details}."
    elif floor == Outcome.NEEDS_REVIEW:
        details = "; ".join(f"{f['code']}: {f['message']}" for f in findings if f["severity"] == "WARNING")
        rationale = (f"Held for review ({fired}). {details or 'Policy requires a human decision'}. "
                     "Recommend a person confirm these points with the vendor before paying.")
    elif policy["vp_scrutiny"]:
        rationale = (f"Approved under VP scrutiny ({fired}): no CRITICAL or WARNING findings; "
                     "items, vendor, and totals reconcile.")
    else:
        rationale = f"Approved ({fired}): no blocking findings."
    return Decision(outcome=floor, rationale=rationale, rules_applied=rules, confidence=1.0)


def critic_review(messages: list[BaseMessage]) -> Critique:
    policy = read_block(messages, "policy")
    draft = Decision.model_validate(read_block(messages, "draft"))
    floor = Outcome(policy["floor"])
    issues = []
    if STRICTNESS[draft.outcome] < STRICTNESS[floor]:
        issues.append(f"Draft outcome {draft.outcome} is looser than the policy floor {floor}.")
    issues += [f"Rationale does not name fired rule {rule}." for rule in policy["rules"] if rule not in draft.rationale]
    return Critique(passes=not issues, issues=issues, suggested_outcome=floor if issues else None)


def register_offline() -> None:
    register_handler(Decision, approval_draft)
    register_handler(Critique, critic_review)
