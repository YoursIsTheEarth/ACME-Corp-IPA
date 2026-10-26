"""Shared helpers for the payment tests (disposition stand-ins and table readers)."""

from decimal import Decimal

from acme.models import Decision, Outcome
from acme.payments import queue_payment, record_processed

APPROVE = Decision(outcome=Outcome.APPROVE, rationale="All checks passed.", decided_by="Auto (rules)")


def make_run(conn, run_id, status="Deciding", stage="Deciding", uploaded_at="2026-01-31T00:00:00+00:00"):
    conn.execute("INSERT INTO invoice_runs (id, file_name, uploaded_at, status, stage) VALUES (?, ?, ?, ?, ?)",
                 (run_id, f"{run_id}.txt", uploaded_at, status, stage))
    conn.commit()


def approve(conn, run_id, invoice, decision=APPROVE):
    """Disposition for an APPROVE: the processed row, then the queue row."""
    make_run(conn, run_id)
    record_processed(run_id, invoice, Outcome.APPROVE)
    return queue_payment(run_id, invoice, decision)


def queue_rows(conn, run_id=None):
    sql = "SELECT * FROM payment_queue" + (" WHERE run_id = ?" if run_id else "") + " ORDER BY id"
    return [dict(r) for r in conn.execute(sql, (run_id,) if run_id else ())]


def run_row(conn, run_id):
    return dict(conn.execute("SELECT * FROM invoice_runs WHERE id = ?", (run_id,)).fetchone())


def revised(invoice, total, revision=1):
    return invoice.model_copy(update={"total": Decimal(total), "revision": revision})
