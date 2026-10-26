"""Graph nodes. Each calls one capability and returns only the state fields it owns.

Stage writes (`invoice_runs.stage`, `status = Processing`) happen as nodes start; outcome
writes happen only in `disposition`, through the payment-processing disposition tools.
The graph never calls `mock_payment`.
"""

import json
import logging
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from langgraph.types import interrupt

from acme import payments
from acme.approval import apply_policy, run_approval
from acme.approval.policy import REVISION_PAID_LOWER
from acme.db import connect
from acme.graph.state import WorkflowState
from acme.ingestion import ExtractedInvoice, ingest
from acme.logging import audit, dumps, read_trace
from acme.models import Decision, FindingCode, Outcome, Severity
from acme.normalization import normalize
from acme.payments._store import immediate, resolve_run
from acme.payments.revisions import money
from acme.validation import ValidationContext, detect_duplicate, run_checks, run_validation
from acme.validation.agent import dedupe

log = logging.getLogger(__name__)

AUTO = "Auto (rules)"
HUMAN_REVIEW = "HUMAN_REVIEW"

EventCallback = Callable[[str, dict[str, Any]], None]
# Optional listener for stage/outcome events (the API publishes them over SSE); None for the CLI.
on_event_var: ContextVar[EventCallback | None] = ContextVar("acme_on_event", default=None)


def emit(name: str, data: dict[str, Any]) -> None:
    callback = on_event_var.get()
    if callback is None:
        return
    try:
        callback(name, data)
    except Exception:  # a broken listener must never break a run
        log.exception("workflow_event_listener_failed", extra={"data": {"event": name}})


def set_stage(run_id: str, stage: str) -> None:
    conn = connect()
    try:
        conn.execute("UPDATE invoice_runs SET stage = ?, status = 'Processing' WHERE id = ?", (stage, run_id))
        conn.commit()
    finally:
        conn.close()
    emit("invoice.stage_changed", {"run_id": run_id, "stage": stage, "status": "Processing"})


def traced(state: WorkflowState, agent: str, event: str, payload: dict[str, Any],
           persist: bool = True) -> list[dict[str, Any]]:
    """`state.trace` plus one entry; also written to `audit_log` unless the capability already did."""
    if persist:
        audit(state.run_id, agent, event, payload)
    return [*state.trace, json.loads(dumps({"agent": agent, "event": event, **payload}))]


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


# --- Ingestion and Normalizer ----------------------------------------------------------------

def ingest_node(state: WorkflowState) -> dict[str, Any]:
    """Ingestion agent; its self-correction loop (max 2 retries, F4) runs inside `ingest()`."""
    set_stage(state.run_id, "Extracting")
    result = ingest(state.file_path, run_id=state.run_id)
    attempts = [e["payload"] for e in read_trace(state.run_id) if e["event"] == "extraction_attempt"]
    errors = [a.get("outcome") for a in attempts[-result.attempts:] if a.get("outcome") != "accepted"]
    payload = {"format": result.source_format, "attempts": result.attempts, "retries": result.retries,
               "errors": errors, "accepted": result.extracted is not None}
    return {
        "raw_text": result.raw_text,
        "source_format": result.source_format,
        "extracted": result.extracted.model_dump() if result.extracted is not None else None,
        "findings": [*state.findings, *result.findings],
        "retries": result.retries,
        "trace": traced(state, "ingestion", "ingestion.result", payload),
    }


def normalize_node(state: WorkflowState) -> dict[str, Any]:
    # normalize() writes its own `normalizer/normalized` audit row.
    invoice, findings = normalize(ExtractedInvoice.model_validate(state.extracted), run_id=state.run_id)
    payload = {
        "invoice_number": invoice.invoice_number if invoice else None,
        "skus": [{"raw_name": i.raw_name, "sku": i.sku} for i in invoice.line_items] if invoice else [],
        "findings": [f.code for f in findings],
    }
    return {"invoice": invoice, "findings": [*state.findings, *findings],
            "trace": traced(state, "normalizer", "normalizer.result", payload, persist=False)}


# --- Validation and Approval -----------------------------------------------------------------

def validate_node(state: WorkflowState) -> dict[str, Any]:
    """LLM tool loop plus the deterministic sweep (`run_validation`). If the LLM fails, checks still run."""
    set_stage(state.run_id, "Validating")
    try:
        new = run_validation(state)
        return {"findings": new.findings, "revision_context": new.revision_context, "trace": new.trace}
    except Exception as exc:  # provider outage etc.: handoff rule 2 still holds without the LLM
        log.exception("validation_agent_failed")
        ctx = ValidationContext.load()
        _, revision_ctx = detect_duplicate(state.invoice, ctx)
        findings = dedupe([*state.findings, *run_checks(state.invoice, ctx)])
        return {"findings": findings, "revision_context": revision_ctx,
                "trace": traced(state, "validation", "validation.fallback", {
                    "error": _error(exc), "findings": [f.model_dump(mode="json") for f in findings]})}


def approve_node(state: WorkflowState) -> dict[str, Any]:
    """Rules-engine floor, AI VP draft, Critic revision loop (max 2), tighten-only clamp (`run_approval`)."""
    set_stage(state.run_id, "Deciding")
    try:
        new = run_approval(state)
        return {"decision_draft": new.decision_draft, "critique": new.critique, "decision": new.decision,
                "trace": new.trace}
    except Exception as exc:  # no AI VP: the floor decides, and VP scrutiny goes to a person
        log.exception("approval_agent_failed")
        policy = apply_policy(state.invoice, state.findings, state.revision_context)
        outcome = Outcome.NEEDS_REVIEW if policy.vp_scrutiny else policy.floor
        decision = Decision(outcome=outcome, rules_applied=list(policy.rules), decided_by=AUTO,
                            rationale=f"AI VP unavailable ({type(exc).__name__}); decided by the rules engine "
                                      f"({', '.join(policy.rules)}).")
        return {"decision": decision,
                "trace": traced(state, "approval", "approval.fallback", {"error": _error(exc), "decision": decision})}


# --- Disposition and review hold -------------------------------------------------------------

def _no_invoice_decision(state: WorkflowState) -> Decision:
    policy = apply_policy(None, state.findings)
    reasons = "; ".join(f.message for f in state.findings if f.severity == Severity.CRITICAL)
    return Decision(outcome=policy.floor, rationale=f"Rejected ({', '.join(policy.rules)}). {reasons}".strip(),
                    rules_applied=list(policy.rules), decided_by=AUTO)


def _hold(state: WorkflowState, decision: Decision) -> dict[str, Any]:
    invoice, draft = state.invoice, state.decision_draft
    held = [f for f in state.findings if f.severity != Severity.INFO]
    details: dict[str, Any] = {
        "findings": [f.code for f in held],
        "ai_recommendation": (draft or decision).outcome,
        "ai_rationale": (draft or decision).rationale,
    }
    if REVISION_PAID_LOWER in decision.rules_applied:
        kind = "credit"
        paid = state.revision_context.paid_amount
        details |= {"overpaid": money(paid - invoice.total), "paid_amount": money(paid)}
        reason = f"Revision lowers a paid total: {details['overpaid']} overpaid; confirm a credit or refund"
    else:
        kind = "warning"
        reason = "; ".join(f"{f.code}: {f.message}" for f in held) or decision.rationale
    payments.enqueue_review(state.run_id, reason, kind, details)
    return {"held": True, "hold_kind": kind, "reason": reason}


def _run_status(run_id: str) -> tuple[str | None, str | None]:
    conn = connect()
    try:
        row = conn.execute("SELECT status, final_status FROM invoice_runs WHERE id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    return (row["status"], row["final_status"]) if row else (None, None)


def _credit_confirmed(run_id: str, decided_by: str | None) -> None:
    conn = connect()
    try:
        with immediate(conn):
            resolve_run(conn, run_id, "Credit confirmed", decided_by)
    finally:
        conn.close()


def disposition_node(state: WorkflowState) -> dict[str, Any]:
    """The only exit: record the invoice, supersede an unpaid original, then queue / reject / hold."""
    run_id, invoice = state.run_id, state.invoice
    decision = state.decision or _no_invoice_decision(state)
    result: dict[str, Any] = {"held": False}
    if invoice is not None:
        payments.record_processed(run_id, invoice, decision.outcome)
        if any(f.code == FindingCode.REVISION for f in state.findings):
            result["superseded"] = payments.supersede_original(invoice, run_id)

    if decision.outcome == Outcome.REJECT:
        payments.record_rejection(run_id, decision, state.findings)
    elif decision.outcome == Outcome.NEEDS_REVIEW:
        result |= _hold(state, decision)
    elif state.hold_kind == "credit":  # reviewer confirmed the vendor's credit or refund: nothing to pay
        _credit_confirmed(run_id, decision.decided_by)
    else:
        queued = payments.queue_payment(run_id, invoice, decision)
        result |= {"action": queued.action, "row_id": queued.row_id, "kind": queued.kind,
                   "amount_usd": queued.amount, "reason": queued.reason}
        if queued.action == "held":
            result |= {"held": True, "hold_kind": payments.review_hold(run_id).kind}

    status, final_status = _run_status(run_id)
    result |= {"status": status, "final_status": final_status}
    trace = traced(state, "disposition", "disposition.outcome",
                   {"outcome": decision.outcome, "decided_by": decision.decided_by, **result})
    event = "invoice.resolved" if status == "Resolved" else "invoice.stage_changed"
    emit(event, {"run_id": run_id, "stage": status, "status": status, "final_status": final_status})
    return {"decision": decision, "payment_result": json.loads(dumps(result)), "trace": trace}


def review_hold_node(state: WorkflowState) -> dict[str, Any]:
    """Pause until a person decides (F17, F28). Resumed with {"decision", "reviewer", "rationale"}."""
    hold = payments.review_hold(state.run_id)
    invoice = state.invoice
    answer = interrupt({
        "run_id": state.run_id,
        "kind": hold.kind if hold else None,
        "reason": hold.reason if hold else None,
        "details": json.loads(dumps(hold.details)) if hold else {},
        "invoice_number": invoice.invoice_number if invoice else None,
        "vendor": invoice.vendor_name if invoice else None,
        "total_usd": str(invoice.total) if invoice else None,
    })
    approve = answer["decision"] == "approve"
    previous = state.decision.rules_applied if state.decision else []
    decision = Decision(outcome=Outcome.APPROVE if approve else Outcome.REJECT, rationale=answer["rationale"],
                        rules_applied=[*previous, HUMAN_REVIEW], decided_by=answer["reviewer"])
    # resume_review already wrote the `review.decision` audit row.
    return {"decision": decision, "hold_kind": hold.kind if hold else None,
            "trace": traced(state, "reviewer", "review.decision",
                            {"decision": answer["decision"], "reviewer": answer["reviewer"],
                             "rationale": answer["rationale"]}, persist=False)}
