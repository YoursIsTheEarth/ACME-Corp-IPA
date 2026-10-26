"""Payment Executor (F16): the only code that calls `mock_payment`.

    result = run_batch("pay_all", "Dana")            # raises BatchAlreadyRunning if one is running
    run_batch("pay_selected", "Dana", ids=[3, 5])
    pay_now_if_immediate()                             # delay off: an `immediate` batch of what is payable now
    recover_interrupted_batch()                        # at startup, before any batch
    resume_payment_failure(run_id, approve=True)       # decision on a payment-failure hold
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from acme.db import connect
from acme.logging import audit
from acme.payments import events, mock_bank
from acme.payments._store import BATCH_LOCK, immediate, resolve_run, row_key, utcnow
from acme.payments.queue import enqueue_review
from acme.payments.revisions import money
from acme.settings import get_settings

log = logging.getLogger(__name__)

AGENT = "payment_executor"
TRIGGERS = ("end_of_day", "idle", "immediate", "pay_all", "pay_selected", "pay_now")
SYSTEM_TRIGGERS = ("end_of_day", "idle", "immediate")
Trigger = Literal["end_of_day", "idle", "immediate", "pay_all", "pay_selected", "pay_now"]


class BatchAlreadyRunning(RuntimeError):
    """Another batch holds the lock; the API maps this to 409 and the scheduler skips the tick."""


class InvalidBatchRequest(ValueError):
    """Bad trigger, `released_by` outside 1-50 characters after trimming, or missing ids."""


@dataclass(frozen=True)
class RowResult:
    row_id: int
    status: Literal["paid", "already_paid", "failed", "escalated", "skipped"]
    run_id: str | None = None
    invoice_number: str | None = None
    amount_usd: Decimal | None = None
    payment_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class BatchResult:
    batch_id: str
    trigger: str
    released_by: str
    count: int
    total_usd: Decimal
    failed_count: int
    results: list[RowResult] = field(default_factory=list)


def is_batch_running() -> bool:
    return BATCH_LOCK.locked()


def _released_by(trigger: str, released_by: str | None) -> str:
    if trigger not in TRIGGERS:
        raise InvalidBatchRequest(f"unknown trigger {trigger!r}")
    if trigger in SYSTEM_TRIGGERS:
        return "System"
    name = (released_by or "").strip()
    if not 1 <= len(name) <= 50:
        raise InvalidBatchRequest("released_by must be 1 to 50 characters")
    return name


def run_batch(trigger: Trigger, released_by: str | None = None, ids: list[int] | None = None) -> BatchResult:
    """Run one batch. `end_of_day`, `idle`, `pay_all` take every payable row; `pay_selected`/`pay_now` only `ids`;
    `immediate` every `queued` row plus `failed` ones last tried at least `PAYMENT_IDLE_DELAY_S` ago.

    Payable: `queued`, or `failed` with attempts left. Selected rows move to `paying` under
    `BEGIN IMMEDIATE`, then each is re-checked, paid once via `mock_payment`, and written to `payments`.
    Always writes a `payment_batches` record (per-row results go to the `batch.finished` audit event).
    Afterwards, with payment delay off, rows that became payable meanwhile are paid by an `immediate` batch.
    """
    name = _released_by(trigger, released_by)
    scoped = trigger in ("pay_selected", "pay_now")
    if scoped and not ids:
        raise InvalidBatchRequest(f"{trigger} needs row ids")
    if not BATCH_LOCK.acquire(blocking=False):
        raise BatchAlreadyRunning("a payment batch is already running")
    try:
        conn = connect()
        try:
            result = _run(conn, trigger, name, list(ids) if scoped else None)
        finally:
            conn.close()
    finally:
        BATCH_LOCK.release()
    pay_now_if_immediate()  # drain: rows approved while this batch ran
    return result


def immediate_scope(conn: sqlite3.Connection, max_attempts: int) -> list[int]:
    """The `immediate` scope: every `queued` row, plus `failed` rows with attempts left whose last attempt
    (their batch's finish) was at least `PAYMENT_IDLE_DELAY_S` ago."""
    wait = timedelta(seconds=get_settings().payment_idle_delay_s)
    cutoff = (datetime.now(timezone.utc) - wait).isoformat(timespec="microseconds")
    rows = conn.execute(
        "SELECT q.id FROM payment_queue q LEFT JOIN payment_batches b ON b.batch_id = q.batch_id "
        "WHERE q.status = 'queued' OR (q.status = 'failed' AND q.attempts < ? "
        "AND (b.batch_id IS NULL OR COALESCE(b.finished_at, b.started_at) <= ?)) ORDER BY q.id",
        (max_attempts, cutoff))
    return [r["id"] for r in rows.fetchall()]


def pay_now_if_immediate(conn: sqlite3.Connection | None = None) -> BatchResult | None:
    """With payment delay off and rows payable under the `immediate` scope, run an `immediate` batch.

    Returns None when delay is on, nothing is payable, or another batch is running (`BatchAlreadyRunning`):
    that batch pays the rows when it finishes. Released by System.
    """
    from acme.admin import load_payment_timing  # acme.admin imports this package

    own = conn is None
    conn = conn or connect()
    try:
        if load_payment_timing(conn).delay_payments:
            return None
        if not immediate_scope(conn, get_settings().payment_max_attempts):
            return None
    finally:
        if own:
            conn.close()
    try:
        return run_batch("immediate")
    except BatchAlreadyRunning:
        return None


def _run(conn: sqlite3.Connection, trigger: str, released_by: str, ids: list[int] | None) -> BatchResult:
    max_attempts = get_settings().payment_max_attempts
    results: list[RowResult] = []
    with immediate(conn):
        number = conn.execute("SELECT COUNT(*) FROM payment_batches").fetchone()[0] + 1
        batch_id = f"B-{number:04d}"
        started_at = utcnow()
        conn.execute("INSERT INTO payment_batches (batch_id, trigger, released_by, started_at) VALUES (?, ?, ?, ?)",
                     (batch_id, trigger, released_by, started_at))
        payable = "(status = 'queued' OR (status = 'failed' AND attempts < ?))"
        if trigger == "immediate":
            selected = immediate_scope(conn, max_attempts)
        elif ids is None:
            rows = conn.execute(f"SELECT id FROM payment_queue WHERE {payable} ORDER BY id", (max_attempts,))
            selected = [r["id"] for r in rows.fetchall()]
        else:
            marks = ",".join("?" * len(ids))
            rows = conn.execute(f"SELECT id FROM payment_queue WHERE {payable} AND id IN ({marks}) ORDER BY id",
                                (max_attempts, *ids))
            selected = [r["id"] for r in rows.fetchall()]
        results += [RowResult(i, "skipped", error="not queued or failed") for i in (ids or []) if i not in selected]
        conn.executemany("UPDATE payment_queue SET status = 'paying', batch_id = ? WHERE id = ?",
                         [(batch_id, row_id) for row_id in selected])
    audit(None, AGENT, "batch.started", {"batch_id": batch_id, "trigger": trigger, "released_by": released_by,
                                         "row_ids": selected}, conn=conn)
    events.emit("batch.started", {"batch_id": batch_id, "trigger": trigger, "released_by": released_by,
                                  "row_ids": selected})

    for row_id in selected:
        results.append(_pay_row(conn, batch_id, row_id, max_attempts))

    paid = [r for r in results if r.status == "paid"]
    total = sum((r.amount_usd for r in paid), Decimal("0"))
    failed = sum(r.status in ("failed", "escalated") for r in results)
    with immediate(conn):
        conn.execute("UPDATE payment_batches SET finished_at = ?, count = ?, total_usd = ?, failed_count = ? "
                     "WHERE batch_id = ?", (utcnow(), len(paid), money(total), failed, batch_id))
    result = BatchResult(batch_id, trigger, released_by, len(paid), money(total), failed, results)
    summary = {"batch_id": batch_id, "trigger": trigger, "released_by": released_by, "count": len(paid),
               "total_usd": money(total), "failed_count": failed, "results": results}
    audit(None, AGENT, "batch.finished", summary, conn=conn)
    events.emit("batch.finished", summary)
    return result


def _recheck(conn: sqlite3.Connection, batch_id: str, row_id: int) -> tuple[sqlite3.Row | None, str | None]:
    """The row if it may still be paid, else the reason to skip it (cancelled row or Superseded run)."""
    row = conn.execute("SELECT q.*, r.final_status FROM payment_queue q LEFT JOIN invoice_runs r ON r.id = q.run_id "
                       "WHERE q.id = ?", (row_id,)).fetchone()
    if row is None or row["status"] != "paying" or row["batch_id"] != batch_id:
        return None, f"row is {row['status'] if row else 'missing'}"
    if row["final_status"] == "Superseded":
        conn.execute("UPDATE payment_queue SET status = 'cancelled', last_error = 'superseded' WHERE id = ?",
                     (row_id,))
        conn.commit()
        return None, "invoice superseded"
    return row, None


def _mark_paid(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    conn.execute("UPDATE payment_queue SET status = 'paid' WHERE id = ?", (row["id"],))
    resolve_run(conn, row["run_id"], "Revised" if row["kind"] == "delta" else "Paid")


def _pay_row(conn: sqlite3.Connection, batch_id: str, row_id: int, max_attempts: int) -> RowResult:
    row, skip = _recheck(conn, batch_id, row_id)
    if row is None:
        return RowResult(row_id, "skipped", error=skip)
    key, amount = row_key(row), money(row["amount_usd"])
    base = dict(run_id=row["run_id"], invoice_number=row["invoice_number"], amount_usd=amount)
    if conn.execute("SELECT 1 FROM payments WHERE idempotency_key = ?", (key,)).fetchone():
        with immediate(conn):
            _mark_paid(conn, row)
        audit(row["run_id"], AGENT, "payment.already_paid", {"row_id": row_id, "idempotency_key": key}, conn=conn)
        return RowResult(row_id, "already_paid", error="already paid", **base)

    try:
        response = mock_bank.mock_payment(row["vendor"], amount)
        if not isinstance(response, dict) or response.get("status") != "success":
            raise RuntimeError(f"payment not successful: {response!r}")
    except Exception as exc:  # any bank error is a failed attempt, never a crash of the batch
        return _fail(conn, row, f"{type(exc).__name__}: {exc}", max_attempts, base)

    try:
        with immediate(conn):
            payment_no = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM payments").fetchone()[0]
            payment_id = f"PAY-{payment_no:06d}"
            conn.execute("INSERT INTO payments (idempotency_key, vendor, amount_usd, paid_at, batch_id, payment_id) "
                         "VALUES (?, ?, ?, ?, ?, ?)", (key, row["vendor"], amount, utcnow(), batch_id, payment_id))
            _mark_paid(conn, row)
    except sqlite3.IntegrityError:  # UNIQUE key backstop: another writer paid it first
        with immediate(conn):
            _mark_paid(conn, row)
        return RowResult(row_id, "already_paid", error="already paid", **base)
    data = {"row_id": row_id, "payment_id": payment_id, "batch_id": batch_id, "idempotency_key": key,
            "vendor": row["vendor"], "kind": row["kind"], **base}
    audit(row["run_id"], AGENT, "payment.created", data, conn=conn)
    events.emit("payment.created", data)
    return RowResult(row_id, "paid", payment_id=payment_id, **base)


def _fail(conn: sqlite3.Connection, row: sqlite3.Row, error: str, max_attempts: int,
          base: dict[str, Any]) -> RowResult:
    attempts = row["attempts"] + 1
    escalate = attempts >= max_attempts
    with immediate(conn):
        conn.execute("UPDATE payment_queue SET status = ?, attempts = ?, last_error = ? WHERE id = ?",
                     ("cancelled" if escalate else "failed", attempts, error, row["id"]))
    audit(row["run_id"], AGENT, "payment.failed", {"row_id": row["id"], "attempts": attempts, "error": error},
          conn=conn)
    if not escalate:
        return RowResult(row["id"], "failed", error=error, **base)
    enqueue_review(row["run_id"], f"payment failed {attempts} times: {error}", "payment_failure",
                   {"row_id": row["id"], "last_error": error, "attempts": attempts}, conn=conn)
    return RowResult(row["id"], "escalated", error=error, **base)


def recover_interrupted_batch() -> dict[str, int]:
    """Startup: rows left `paying` become `paid` if their key is in `payments`, else `queued` ("interrupted").

    No attempt is counted. Unfinished batch records are closed with what the ledger shows.
    Returns `{"paid": n, "requeued": m}`.
    """
    with BATCH_LOCK:
        conn = connect()
        try:
            paid = requeued = 0
            with immediate(conn):
                for row in conn.execute("SELECT * FROM payment_queue WHERE status = 'paying'").fetchall():
                    if conn.execute("SELECT 1 FROM payments WHERE idempotency_key = ?", (row_key(row),)).fetchone():
                        _mark_paid(conn, row)
                        paid += 1
                    else:
                        conn.execute("UPDATE payment_queue SET status = 'queued', last_error = 'interrupted', "
                                     "batch_id = NULL WHERE id = ?", (row["id"],))
                        requeued += 1
                for batch in conn.execute("SELECT batch_id FROM payment_batches WHERE finished_at IS NULL").fetchall():
                    amounts = [Decimal(r["amount_usd"]) for r in conn.execute(
                        "SELECT amount_usd FROM payments WHERE batch_id = ?", (batch["batch_id"],))]
                    conn.execute("UPDATE payment_batches SET finished_at = ?, count = ?, total_usd = ? "
                                 "WHERE batch_id = ?",
                                 (utcnow(), len(amounts), money(sum(amounts, Decimal("0"))), batch["batch_id"]))
            if paid or requeued:
                audit(None, AGENT, "batch.recovered", {"paid": paid, "requeued": requeued}, conn=conn)
            return {"paid": paid, "requeued": requeued}
        finally:
            conn.close()


def resume_payment_failure(run_id: str, approve: bool, reviewer: str | None = None,
                           rationale: str | None = None) -> int | None:
    """Decide a payment-failure hold. Approve: a fresh `queued` row (0 attempts, same kind, amount, and key).

    Reject: the run resolves Rejected with the last error and the reviewer's rationale; nothing is queued.
    Returns the new row id on approve, else None.
    """
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM payment_queue WHERE run_id = ? AND status = 'cancelled' "
                           "AND attempts >= ? ORDER BY id DESC LIMIT 1",
                           (run_id, get_settings().payment_max_attempts)).fetchone()
        if row is None:
            raise ValueError(f"run {run_id} has no payment-failure hold")
        if not approve:
            with immediate(conn):
                resolve_run(conn, run_id, "Rejected", reviewer)
            audit(run_id, AGENT, "rejection.recorded", {
                "invoice_number": row["invoice_number"], "vendor": row["vendor"], "final_status": "Rejected",
                "outcome": "REJECT", "rationale": rationale, "decided_by": reviewer,
                "reason": "payment failed", "last_error": row["last_error"], "findings": [],
            }, conn=conn)
            return None
        with immediate(conn):
            new_id = conn.execute(
                "INSERT INTO payment_queue (run_id, invoice_number, revision, vendor, amount_usd, kind, status, "
                "attempts, queued_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?)",
                (run_id, row["invoice_number"], row["revision"], row["vendor"], row["amount_usd"], row["kind"],
                 utcnow()),
            ).lastrowid
            conn.execute("UPDATE invoice_runs SET status = 'Queued for payment', stage = 'Queued for payment', "
                         "decided_by = COALESCE(?, decided_by) WHERE id = ?", (reviewer, run_id))
        data = {"row_id": new_id, "run_id": run_id, "invoice_number": row["invoice_number"], "kind": row["kind"],
                "amount_usd": money(row["amount_usd"]), "vendor": row["vendor"], "requeued_from": row["id"]}
        audit(run_id, AGENT, "payment.queued", data, conn=conn)
        events.emit("payment.queued", data)
        return new_id
    finally:
        conn.close()
