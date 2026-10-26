"""Shared plumbing for the payment modules: the batch lock, transactions, keys, and run updates."""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from acme.payees import set_outcome
from acme.validation.context import normalize_name

# One batch at a time per process (design D2). Disposition also takes it to read a `paying` original.
BATCH_LOCK = threading.Lock()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@contextmanager
def immediate(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One `BEGIN IMMEDIATE` write transaction; commits on success, rolls back on error."""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def idempotency_key(vendor: str, invoice_number: str, revision: int, kind: str) -> str:
    """`vendor|invoice_number|revision`, vendor trimmed and case-folded; delta rows add `|delta`."""
    key = f"{normalize_name(vendor)}|{invoice_number}|{revision}"
    return f"{key}|delta" if kind == "delta" else key


def row_key(row: sqlite3.Row) -> str:
    return idempotency_key(row["vendor"], row["invoice_number"], row["revision"], row["kind"])


def resolve_run(conn: sqlite3.Connection, run_id: str, final_status: str, decided_by: str | None = None) -> None:
    """Mark a run resolved with `final_status` (keeps an earlier `decided_by` when none is given), in the payee
    ledger too."""
    conn.execute(
        "UPDATE invoice_runs SET status = 'Resolved', stage = 'Resolved', final_status = ?, "
        "decided_by = COALESCE(?, decided_by), completed_at = ? WHERE id = ?",
        (final_status, decided_by, utcnow(), run_id),
    )
    set_outcome(conn, run_id, final_status)
