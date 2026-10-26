"""Disposition tools (F16, F17, F39): the only writers of outcomes for a finished run.

    record_processed(run_id, invoice, outcome)        # every outcome that has an invoice
    supersede_original(revision_invoice, run_id)      # every REVISION, whatever its outcome
    queue_payment(run_id, invoice, decision)          # APPROVE -> payment_queue row (never pays)
    record_rejection(run_id, decision, findings)      # REJECT -> Rejected or Duplicate + rejection log
    enqueue_review(run_id, reason, kind)              # NEEDS_REVIEW, credit hold, payment failure, payee threshold
    record_payee_invoice(run_id, invoice, outcome)    # every outcome that has an invoice: the payee ledger
    apply_payee_flags(run_id, finding)                # PAYEE_CUMULATIVE_THRESHOLD: flag the other contributors

Each function opens its own connection unless `conn` is given.
"""

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from acme import payees
from acme.db import connect
from acme.logging import audit
from acme.models import Decision, Finding, FindingCode, Invoice, Outcome
from acme.payments import events
from acme.payments._store import BATCH_LOCK, immediate, resolve_run, utcnow
from acme.payments.revisions import OriginalPayment, RevisionKind, money, resolve_revision
from acme.settings import get_settings
from acme.validation.context import ValidationContext, content_hash

log = logging.getLogger(__name__)

AGENT = "disposition"
HoldKind = Literal["warning", "credit", "payment_failure", "payee_threshold"]
HOLD_KINDS = ("warning", "credit", "payment_failure", "payee_threshold")
PAYEE_HOLD_REASON = "Payee cumulative threshold"
PULLED = "pulled: payee cumulative threshold"


@dataclass(frozen=True)
class QueueResult:
    """What `queue_payment` did: `queued` a row, recorded the run `revised` (no payment due), or `held` it."""

    action: Literal["queued", "revised", "held"]
    row_id: int | None = None
    kind: str | None = None
    amount: Decimal | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ReviewHold:
    kind: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@contextmanager
def _connection(conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    if conn is not None:
        yield conn
        return
    own = connect()
    try:
        yield own
    finally:
        own.close()


@contextmanager
def _batch_lock_wait() -> Iterator[bool]:
    """Wait for any in-flight batch (WAIT_FOR_PAYMENT); yields False on timeout."""
    acquired = BATCH_LOCK.acquire(timeout=get_settings().payment_lock_timeout_s)
    try:
        yield acquired
    finally:
        if acquired:
            BATCH_LOCK.release()


def record_processed(run_id: str, invoice: Invoice, outcome: Outcome | str,
                     conn: sqlite3.Connection | None = None) -> None:
    """Write the `processed_invoices` row validation reads, and the run's identity and `total_usd`.

    Uses `vendor_key` and `content_hash` per the validation contract. The first run to claim a
    (vendor, number, revision) keeps it; the same run re-recording (after a review) updates its outcome.
    """
    with _connection(conn) as c:
        vendor = ValidationContext.load(c).vendor_key(invoice.vendor_name)
        with immediate(c):
            c.execute(
                "INSERT INTO processed_invoices (vendor, invoice_number, revision, content_hash, outcome, run_id) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (vendor, invoice_number, revision) DO UPDATE SET "
                "outcome = excluded.outcome, content_hash = excluded.content_hash "
                "WHERE processed_invoices.run_id = excluded.run_id",
                (vendor, invoice.invoice_number, invoice.revision, content_hash(invoice), str(outcome), run_id),
            )
            c.execute("UPDATE invoice_runs SET invoice_number = ?, vendor = ?, total_usd = ? WHERE id = ?",
                      (invoice.invoice_number, invoice.vendor_name, money(invoice.total), run_id))


def _earlier_runs(c: sqlite3.Connection, ctx: ValidationContext, invoice: Invoice) -> list[str]:
    vendor = ctx.vendor_key(invoice.vendor_name)
    return [p.run_id for p in ctx.processed
            if p.vendor == vendor and p.invoice_number == invoice.invoice_number
            and p.revision < invoice.revision and p.run_id is not None]


def _paid_before(ctx: ValidationContext, invoice: Invoice) -> Decimal | None:
    """Total already paid for earlier revisions of this invoice (delta rows included); None if nothing."""
    vendor = ctx.vendor_key(invoice.vendor_name)
    paid = None
    for payment in ctx.payments:
        parts = payment.idempotency_key.split("|")
        if parts[-1] == "delta":
            parts = parts[:-1]
        if (len(parts) >= 3 and parts[-2] == invoice.invoice_number and parts[-1].isdigit()
                and int(parts[-1]) < invoice.revision and ctx.vendor_key(payment.vendor) == vendor):
            paid = (paid or Decimal("0")) + payment.amount_usd
    return paid


def _original_payment(c: sqlite3.Connection, ctx: ValidationContext, earlier: list[str],
                      invoice: Invoice) -> OriginalPayment:
    marks = ",".join("?" * len(earlier))
    paying = c.execute(f"SELECT 1 FROM payment_queue WHERE status = 'paying' AND run_id IN ({marks})",
                       earlier).fetchone()
    if paying:
        return OriginalPayment("paying")
    paid = _paid_before(ctx, invoice)
    return OriginalPayment("unpaid") if paid is None else OriginalPayment("paid", paid)


def _supersede(c: sqlite3.Connection, earlier: list[str], invoice: Invoice, revision_run_id: str | None) -> list[str]:
    """Mark unpaid earlier runs Superseded and cancel their payable rows, in one transaction."""
    superseded: list[tuple[str, list[int]]] = []
    with immediate(c):
        for run_id in earlier:
            rows = c.execute("SELECT id, status FROM payment_queue WHERE run_id = ?", (run_id,)).fetchall()
            if any(r["status"] in ("paid", "paying") for r in rows):
                continue  # a paid original stays Paid; a paying one is resolved by its batch
            run = c.execute("SELECT final_status FROM invoice_runs WHERE id = ?", (run_id,)).fetchone()
            cancelled = [r["id"] for r in rows if r["status"] in ("queued", "failed")]
            if run is not None and run["final_status"] == "Superseded" and not cancelled:
                continue
            for row_id in cancelled:
                c.execute("UPDATE payment_queue SET status = 'cancelled', last_error = ? WHERE id = ?",
                          ("superseded by revision", row_id))
            resolve_run(c, run_id, "Superseded")
            superseded.append((run_id, cancelled))
    for run_id, cancelled in superseded:
        finding = Finding(code=FindingCode.SUPERSEDED_BY_REVISION, severity=FindingCode.SUPERSEDED_BY_REVISION.severity,
                          message=f"Superseded by revision {invoice.revision} of {invoice.invoice_number}",
                          evidence={"revision": invoice.revision, "revision_run_id": revision_run_id,
                                    "cancelled_rows": cancelled})
        audit(run_id, AGENT, "invoice.superseded", {"finding": finding}, conn=c)
        for row_id in cancelled:
            events.emit("payment.cancelled", {"row_id": row_id, "run_id": run_id, "reason": "superseded"})
    return [run_id for run_id, _ in superseded]


def supersede_original(revision_invoice: Invoice, revision_run_id: str | None = None,
                       conn: sqlite3.Connection | None = None) -> list[str]:
    """Supersede every unpaid earlier revision (queued, held, or rejected); a paid original is left as is.

    Call at Disposition for any run with a `REVISION` finding, whatever its outcome. Waits for an
    in-flight batch first, so an original whose payment fails mid-batch is still superseded.
    Returns the superseded run ids.
    """
    with _connection(conn) as c:
        with _batch_lock_wait() as acquired:
            if not acquired:
                log.warning("supersede_lock_timeout", extra={"data": {"invoice": revision_invoice.invoice_number}})
            earlier = _earlier_runs(c, ValidationContext.load(c), revision_invoice)
            return _supersede(c, earlier, revision_invoice, revision_run_id) if earlier else []


def _insert_row(c: sqlite3.Connection, run_id: str, invoice: Invoice, decision: Decision,
                kind: str, amount: Decimal) -> int:
    with immediate(c):
        row_id = c.execute(
            "INSERT INTO payment_queue (run_id, invoice_number, revision, vendor, amount_usd, kind, status, "
            "attempts, queued_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?)",
            (run_id, invoice.invoice_number, invoice.revision, invoice.vendor_name, money(amount), kind, utcnow()),
        ).lastrowid
        c.execute("UPDATE invoice_runs SET status = 'Queued for payment', stage = 'Queued for payment', "
                  "final_status = NULL, decided_by = COALESCE(?, decided_by) WHERE id = ?",
                  (decision.decided_by, run_id))
        payees.set_outcome(c, run_id, "Queued for payment")
    data = {"row_id": row_id, "run_id": run_id, "invoice_number": invoice.invoice_number, "kind": kind,
            "amount_usd": money(amount), "vendor": invoice.vendor_name}
    audit(run_id, AGENT, "payment.queued", data, conn=c)
    events.emit("payment.queued", data)
    return row_id


def queue_payment(run_id: str, invoice: Invoice, decision: Decision,
                  conn: sqlite3.Connection | None = None) -> QueueResult:
    """APPROVE: add one `payment_queue` row (kind full, replacement, or delta). Never calls `mock_payment`.

    For a revision, the original's payment state is read under the batch lock and `resolve_revision`
    picks the row: unpaid -> replacement for the full total (any leftover original row is cancelled),
    paid higher -> delta, paid same -> Revised with nothing queued, paid lower -> credit hold, and an
    original still paying after `PAYMENT_LOCK_TIMEOUT_S` -> review hold.
    Re-queuing a run that already has a live or paid row returns that row.
    """
    if decision.outcome != Outcome.APPROVE:
        raise ValueError(f"queue_payment needs an APPROVE decision, got {decision.outcome}")
    with _connection(conn) as c:
        existing = c.execute(
            "SELECT id, kind, amount_usd FROM payment_queue WHERE run_id = ? AND status IN "
            "('queued', 'paying', 'failed', 'paid') ORDER BY id DESC", (run_id,)).fetchone()
        if existing is not None:
            return QueueResult("queued", existing["id"], existing["kind"], Decimal(existing["amount_usd"]))

        ctx = ValidationContext.load(c)
        earlier = _earlier_runs(c, ctx, invoice) if invoice.revision > 0 else []
        if not earlier:
            amount = money(invoice.total)
            return QueueResult("queued", _insert_row(c, run_id, invoice, decision, "full", amount), "full", amount)

        with _batch_lock_wait() as acquired:
            original = (_original_payment(c, ValidationContext.load(c), earlier, invoice)
                        if acquired else OriginalPayment("paying"))
            action = resolve_revision(original, invoice.total)
            if action.kind is RevisionKind.REPLACE:
                _supersede(c, earlier, invoice, run_id)
                row_id = _insert_row(c, run_id, invoice, decision, "replacement", action.amount)
                return QueueResult("queued", row_id, "replacement", action.amount)
            if action.kind is RevisionKind.DELTA:
                row_id = _insert_row(c, run_id, invoice, decision, "delta", action.amount)
                return QueueResult("queued", row_id, "delta", action.amount)

        if action.kind is RevisionKind.REVISED_NO_PAYMENT:
            with immediate(c):
                resolve_run(c, run_id, "Revised", decision.decided_by)
            audit(run_id, AGENT, "revision.no_payment_due", {"paid_amount": original.paid_amount}, conn=c)
            return QueueResult("revised")
        if action.kind is RevisionKind.CREDIT_HOLD:
            reason = f"Revision lowers a paid total: {action.amount} overpaid"
            enqueue_review(run_id, reason, "credit", {"overpaid": action.amount,
                                                      "paid_amount": money(original.paid_amount)}, conn=c)
            return QueueResult("held", amount=action.amount, reason=reason)
        reason = "Original payment still in progress; revision held for review"
        enqueue_review(run_id, reason, "warning", conn=c)
        return QueueResult("held", reason=reason)


def record_rejection(run_id: str, decision: Decision, findings: list[Finding],
                     conn: sqlite3.Connection | None = None) -> str:
    """REJECT: final status Duplicate (if a DUPLICATE finding) or Rejected, plus a `rejection.recorded` event.

    The event holds the invoice identity, rationale, rules applied, and every finding. Nothing is queued.
    Returns the final status.
    """
    final_status = "Duplicate" if any(f.code == FindingCode.DUPLICATE for f in findings) else "Rejected"
    with _connection(conn) as c:
        with immediate(c):
            resolve_run(c, run_id, final_status, decision.decided_by)
        run = c.execute("SELECT invoice_number, vendor FROM invoice_runs WHERE id = ?", (run_id,)).fetchone()
        audit(run_id, AGENT, "rejection.recorded", {
            "invoice_number": run["invoice_number"] if run else None,
            "vendor": run["vendor"] if run else None,
            "final_status": final_status,
            "outcome": decision.outcome,
            "rationale": decision.rationale,
            "rules_applied": decision.rules_applied,
            "decided_by": decision.decided_by,
            "findings": findings,
        }, conn=c)
    return final_status


def enqueue_review(run_id: str, reason: str, kind: HoldKind, details: dict[str, Any] | None = None,
                   conn: sqlite3.Connection | None = None) -> None:
    """Hold a run in Elevated Review: status Awaiting review plus a `review.enqueued` event with the reason.

    Kinds: `warning` (NEEDS_REVIEW), `credit` (revision lowers a paid total), `payment_failure`, and
    `payee_threshold` (an approved payment pulled from the queue by `apply_payee_flags`).
    Pausing the graph is the workflow's job; this only records the hold.
    """
    if kind not in HOLD_KINDS:
        raise ValueError(f"unknown review kind {kind!r}")
    with _connection(conn) as c:
        with immediate(c):
            c.execute("UPDATE invoice_runs SET status = 'Awaiting review', stage = 'Awaiting review', "
                      "final_status = NULL, completed_at = NULL WHERE id = ?", (run_id,))
            payees.set_outcome(c, run_id, "Awaiting review")
        audit(run_id, AGENT, "review.enqueued", {"kind": kind, "reason": reason, "details": details or {}}, conn=c)


def review_hold(run_id: str, conn: sqlite3.Connection | None = None) -> ReviewHold | None:
    """The latest hold recorded for a run (kind, reason, details), or None."""
    with _connection(conn) as c:
        row = c.execute("SELECT payload_json FROM audit_log WHERE run_id = ? AND event = 'review.enqueued' "
                        "ORDER BY ts DESC, id DESC LIMIT 1", (run_id,)).fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload_json"])
    return ReviewHold(payload["kind"], payload["reason"], payload.get("details") or {})


# --- payee registry (design D4, D6) ------------------------------------------------------------

def record_payee_invoice(run_id: str, invoice: Invoice, outcome: Outcome | str,
                         conn: sqlite3.Connection | None = None) -> list[int]:
    """Record the run's invoice in the payee ledger (every outcome, duplicates included); returns its payees."""
    with _connection(conn) as c:
        return payees.record_invoice(c, run_id, invoice, str(outcome))


def payee_threshold_details(run_id: str, finding: Finding) -> dict[str, Any]:
    """A `PAYEE_CUMULATIVE_THRESHOLD` finding as hold details: the total, window, and contributing invoices,
    with the triggering run (`run_id`, the invoice under validation) filled in."""
    evidence = finding.evidence
    return {"message": finding.message, "total": evidence.get("total"), "threshold": evidence.get("threshold"),
            "window": evidence.get("window"), "payees": evidence.get("payees", []), "triggered_by": run_id,
            "invoices": [{**m, "run_id": m.get("run_id") or run_id} for m in evidence.get("invoices", [])]}


def apply_payee_flags(run_id: str, finding: Finding, conn: sqlite3.Connection | None = None) -> list[str]:
    """Flag every other invoice contributing to `run_id`'s `PAYEE_CUMULATIVE_THRESHOLD` finding (design D6).

    Under the batch lock: a `queued` or `failed` payment row is cancelled and the run held in Elevated Review
    (`payee_threshold`); a run already Awaiting review gets the finding and the latest total added to its
    hold; any other run (paid, rejected, superseded, ...) gets a `finding.retroactive` audit entry and keeps
    its status. Returns the run ids pulled from the Payment Queue.
    """
    details = payee_threshold_details(run_id, finding)
    flagged = Finding(code=finding.code, severity=finding.severity, message=finding.message,
                      evidence={**finding.evidence, "invoices": details["invoices"]}, source=finding.source)
    trigger = next((m["invoice_number"] for m in details["invoices"] if m["run_id"] == run_id), None)
    others = list(dict.fromkeys(m["run_id"] for m in details["invoices"] if m["run_id"] != run_id))
    pulled, cancelled = [], []
    with _connection(conn) as c, _batch_lock_wait() as acquired:
        if not acquired:  # a row still `paying` is left to its batch and flagged like a paid one
            log.warning("payee_flags_lock_timeout", extra={"data": {"run_id": run_id}})
        for other in others:
            run = c.execute("SELECT status FROM invoice_runs WHERE id = ?", (other,)).fetchone()
            if run is None:
                continue
            with immediate(c):
                rows = c.execute("SELECT * FROM payment_queue WHERE run_id = ? AND status IN ('queued', 'failed') "
                                 "ORDER BY id", (other,)).fetchall()
                for row in rows:
                    c.execute("UPDATE payment_queue SET status = 'cancelled', last_error = ? WHERE id = ?",
                              (PULLED, row["id"]))
            if rows:
                last = rows[-1]
                enqueue_review(other, PAYEE_HOLD_REASON, "payee_threshold", {
                    "findings": [finding.code], "payee_threshold": details, "pulled": True, "row_id": last["id"],
                    "amount_usd": last["amount_usd"], "ai_recommendation": Outcome.APPROVE,
                    "ai_rationale": f"Approved and queued before {trigger} crossed the payee threshold; "
                                    "pulled from the Payment Queue for review.",
                }, conn=c)
                cancelled += [(row["id"], other) for row in rows]
                pulled.append(other)
            elif run["status"] == "Awaiting review":
                hold = review_hold(other, conn=c)
                held = dict(hold.details) if hold else {}
                reason = hold.reason if hold else PAYEE_HOLD_REASON
                if previous := (held.get("payee_threshold") or {}).get("message"):
                    reason = reason.replace(previous, finding.message)  # the latest total in the reason too
                held["findings"] = list(dict.fromkeys([*held.get("findings", []), finding.code]))
                held["payee_threshold"] = details
                audit(other, AGENT, "review.enqueued", {"kind": hold.kind if hold else "warning", "reason": reason,
                                                        "details": held, "update": True}, conn=c)
            else:
                audit(other, AGENT, "finding.retroactive", {
                    "finding": flagged, "triggered_by": {"run_id": run_id, "invoice_number": trigger},
                    "total": details["total"], "status": run["status"]}, conn=c)
    for row_id, other in cancelled:
        events.emit("payment.cancelled", {"row_id": row_id, "run_id": other, "reason": "payee_threshold"})
    return pulled
