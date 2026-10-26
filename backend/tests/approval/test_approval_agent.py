import inspect
from decimal import Decimal

import pytest

import acme.approval
from acme.approval import agent as approval_agent, run_approval
from acme.approval.agent import AUTO
from acme.models import Critique, Decision, InvoiceState, LineItem, Outcome
from acme.validation import ValidationContext, run_validation
from fake_llm import critic_review
from fakes import ScriptedStructured
from golden_invoices import GOLDEN, GOLDEN_FILES, record_processed

R, N, A = Outcome.REJECT, Outcome.NEEDS_REVIEW, Outcome.APPROVE
AI_VP = "AI VP (grok/grok-4)"  # the fake stands in for the configured Grok model


def big_clean_invoice(golden):
    """Synthetic: no golden file reaches VP scrutiny (every invoice over $10K is rejected)."""
    lines = [LineItem(sku="WidgetA", raw_name="WidgetA", quantity=15, unit_price=Decimal("250.00")),
             LineItem(sku="WidgetB", raw_name="WidgetB", quantity=10, unit_price=Decimal("500.00")),
             LineItem(sku="GadgetX", raw_name="GadgetX", quantity=5, unit_price=Decimal("750.00"))]
    return golden["invoice_1001.txt"].model_copy(update={
        "invoice_number": "INV-9001", "line_items": lines, "subtotal": Decimal("12500.00"),
        "total": Decimal("12500.00")})


def validated(invoice, ctx, run_id="r-test"):
    return run_validation(InvoiceState(run_id=run_id, file_path="x", invoice=invoice), ctx)


def scripted(monkeypatch, drafts, critiques=()):
    fake = ScriptedStructured({Decision: drafts, Critique: list(critiques)})
    monkeypatch.setattr(approval_agent, "get_chat_model", fake)
    return fake


def draft(outcome, rationale="VP_SCRUTINY_OVER_THRESHOLD: checked."):
    return Decision(outcome=outcome, rationale=rationale, confidence=0.8)


def events(state):
    return [(e["event"], e.get("round")) for e in state.trace if e["agent"] == "approval"]


# --- 5.2 fake-model scenarios ----------------------------------------------------------------

def test_critic_passes_first_draft(ctx, golden, monkeypatch):
    scripted(monkeypatch, [draft(A)], [Critique(passes=True)])
    state = run_approval(validated(big_clean_invoice(golden), ctx))
    assert state.decision.outcome == A and state.decision.decided_by == AI_VP
    assert events(state) == [("approval.policy", None), ("approval.draft", 0), ("approval.critique", 0),
                             ("approval.decision", None)]
    critique = next(e for e in state.trace if e["event"] == "approval.critique")
    assert (critique["provider"], critique["model"]) == ("grok", "grok-4")


def test_critic_never_passes_needs_review(ctx, golden, monkeypatch):
    fail = Critique(passes=False, issues=["Rationale does not cite the totals."])
    scripted(monkeypatch, [draft(A, "v1"), draft(A, "v2"), draft(A, "v3")], [fail, fail, fail])
    state = run_approval(validated(big_clean_invoice(golden), ctx))
    assert state.decision.outcome == N
    assert [e for e in events(state) if e[0] in ("approval.draft", "approval.critique")] == [
        ("approval.draft", 0), ("approval.critique", 0), ("approval.draft", 1), ("approval.critique", 1),
        ("approval.draft", 2), ("approval.critique", 2)]
    assert "Critic did not pass after 2 revisions" in state.decision.rationale
    assert "AI recommendation: APPROVE" in state.decision.rationale


def test_revision_sees_the_critique(ctx, golden, monkeypatch):
    fake = scripted(monkeypatch, [draft(A, "v1"), draft(A, "v2")],
                    [Critique(passes=False, issues=["cite the rule"]), Critique(passes=True)])
    state = run_approval(validated(big_clean_invoice(golden), ctx))
    assert state.decision.outcome == A and state.decision.rationale == "v2"
    revision_prompt = [m for schema, m in fake.prompts if schema is Decision][1][-1].content
    assert "<critique>" in revision_prompt and "cite the rule" in revision_prompt


def test_llm_cannot_loosen_reject(ctx, golden, monkeypatch):
    scripted(monkeypatch, [draft(A, "Looks fine to me.")])
    state = run_approval(validated(golden["invoice_1002.txt"], ctx))
    assert state.decision.outcome == R and state.decision_draft.outcome == A
    clamped = [e for e in state.trace if e["event"] == "approval.clamped"]
    assert clamped == [{"agent": "approval", "event": "approval.clamped", "source": "draft", "proposed": "APPROVE",
                        "final": "REJECT", "floor": "REJECT"}]
    assert state.decision.decided_by == AUTO and state.critique is None


def test_critic_cannot_loosen(ctx, golden, monkeypatch):
    scripted(monkeypatch, [draft(N)], [Critique(passes=True, suggested_outcome=A)])
    state = run_approval(validated(big_clean_invoice(golden), ctx))
    assert state.decision.outcome == N


def test_llm_may_tighten(ctx, golden, monkeypatch):
    scripted(monkeypatch, [draft(N, "Unusually large order; confirm with procurement.")])
    state = run_approval(validated(golden["invoice_1001.txt"], ctx))
    assert state.decision.outcome == N and state.decision.decided_by == AI_VP


def test_critic_only_under_vp_scrutiny(ctx, golden, monkeypatch):
    fake = scripted(monkeypatch, [draft(A, "ok")])
    run_approval(validated(golden["invoice_1001.txt"], ctx))
    assert [schema for schema, _ in fake.prompts] == [Decision]


# --- 5.1 prompts ---------------------------------------------------------------------------

def test_prompt_versions_logged(seeded_db, golden):
    state = run_approval(validated(big_clean_invoice(golden), ValidationContext.load(seeded_db), "r-vp"))
    rows = seeded_db.execute("SELECT agent, prompt_version FROM llm_calls WHERE run_id='r-vp' AND agent='approval' "
                             "ORDER BY id").fetchall()
    assert [r["prompt_version"] for r in rows] == ["approval_v1", "critic_v1"]
    assert state.decision.outcome == A


def test_prompts_mark_invoice_untrusted(ctx, golden, monkeypatch):
    fake = scripted(monkeypatch, [draft(A)], [Critique(passes=True)])
    run_approval(validated(big_clean_invoice(golden), ctx))
    for _, messages in fake.prompts:
        assert "untrusted" in messages[0].content
        assert "<untrusted_invoice>" in messages[1].content and "<policy>" in messages[1].content


# --- 5.3 / 5.4 fake model -------------------------------------------------------------------

def test_fake_rationales_for_every_golden_invoice(seeded_db):
    decisions = {}
    for name in GOLDEN_FILES:
        state = run_approval(validated(GOLDEN[name], ValidationContext.load(seeded_db), f"r-{name}"))
        decisions[name] = state.decision
        record_processed(seeded_db, GOLDEN[name], state.decision.outcome, f"r-{name}")
    assert all(d.rationale.strip() for d in decisions.values())
    rejected = decisions["invoice_1016.json"]
    assert "WidgetC" in rejected.rationale and "CRITICAL_UNKNOWN_ITEM" in rejected.rationale
    held = decisions["invoice_1010.txt"]
    assert "AI recommendation:" in held.rationale and "PRICE_VARIANCE" in held.rationale
    assert decisions["invoice_1001.txt"].decided_by == AUTO
    assert len(decisions["invoice_1001.txt"].rationale.splitlines()) == 1


def test_fake_vp_scrutiny_runs_the_critic(ctx, golden):
    state = run_approval(validated(big_clean_invoice(golden), ctx))
    assert events(state) == [("approval.policy", None), ("approval.draft", 0), ("approval.critique", 0),
                             ("approval.decision", None)]
    assert state.critique.passes and state.decision.outcome == A and state.decision.decided_by == AI_VP


def test_fake_critic_rejects_draft_missing_a_rule(ctx, golden, monkeypatch):
    # Approval LLM omits the rule; the fake critic flags it every round.
    fake = ScriptedStructured({Decision: [draft(A, "Fine.")] * 3})
    monkeypatch.setattr(approval_agent, "get_chat_model",
                        lambda role: fake if role == "approval" else _FakeCritic(critic_review))
    state = run_approval(validated(big_clean_invoice(golden), ctx))
    assert state.decision.outcome == N
    assert sum(e["event"] == "approval.critique" for e in state.trace) == 3


class _FakeCritic:
    def __init__(self, handler):
        self.handler = handler

    def with_structured_output(self, schema):
        handler = self.handler

        class _Bound:
            def invoke(self, messages, config=None):
                return handler(messages)
        return _Bound()


# --- 5.5 no money moves --------------------------------------------------------------------

@pytest.mark.parametrize("synthetic", [False, True])
def test_approval_moves_no_money(seeded_db, golden, synthetic):
    invoice = big_clean_invoice(golden) if synthetic else golden["invoice_1001.txt"]
    state = run_approval(validated(invoice, ValidationContext.load(seeded_db)))
    assert state.decision.outcome == A and state.payment_result is None
    for table in ("payments", "payment_queue", "payment_batches"):
        assert seeded_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    for module in (approval_agent, acme.approval.policy):
        assert "mock_payment" not in inspect.getsource(module)
