"""Payment processing (F16, F17 rejection log, F38, F39): the only module that moves money.

Public API -- add-agent-workflow and add-backend-api call only these entry points.

Disposition tools (called by the workflow's Disposition node, in this order):
    record_processed(run_id, invoice, outcome)       every outcome that has an invoice: writes the
                                                     `processed_invoices` row (vendor_key + content_hash)
                                                     and the run's invoice number, vendor, `total_usd`
    supersede_original(revision_invoice, run_id)     every run with a REVISION finding, whatever the outcome
    queue_payment(run_id, invoice, decision)         APPROVE -> QueueResult (queued / revised / held)
    record_rejection(run_id, decision, findings)     REJECT -> "Rejected" or "Duplicate"
    enqueue_review(run_id, reason, kind, details)    NEEDS_REVIEW ("warning"), "credit", "payment_failure"
    review_hold(run_id)                              the latest hold's kind, reason, details

Executor:
    run_batch(trigger, released_by, ids=None)        -> BatchResult; raises BatchAlreadyRunning (409 / skip
                                                     tick) or InvalidBatchRequest (422)
    pay_now_if_immediate()                           delay off: an `immediate` batch of what is payable now
                                                     (after a disposition queues, after every batch, on save)
    is_batch_running()
    immediate_scope(conn, max_attempts)              row ids an `immediate` batch would take now
    recover_interrupted_batch()                      at CLI and API startup, before any batch
    resume_payment_failure(run_id, approve, reviewer, rationale)

Trigger decisions (pure; the caller passes `now`, the settings, and the admin `PaymentTiming`):
    next_batch_time(now, timing), end_of_day_due(now, last_eod_run, timing),
    idle_batch_due(now, runs_snapshot, queue_count, batch_running, settings, timing)
    load_runs_snapshot(conn), payable_count(conn, max_attempts)   inputs for idle_batch_due

Events: `events.subscribe(listener)` receives payment.queued, payment.cancelled, batch.started,
payment.created, batch.finished, and settings.updated (from `acme.admin`).

Single-process assumption: one batch at a time is enforced by an in-process `threading.Lock`.
Across processes (CLI and API at once) the `queued -> paying` claim under `BEGIN IMMEDIATE` and the
UNIQUE `payments.idempotency_key` still prevent paying a row twice, but two batches may overlap.
"""

from acme.payments.events import subscribe
from acme.payments.executor import (
    BatchAlreadyRunning,
    BatchResult,
    InvalidBatchRequest,
    RowResult,
    immediate_scope,
    is_batch_running,
    pay_now_if_immediate,
    recover_interrupted_batch,
    resume_payment_failure,
    run_batch,
)
from acme.payments.queue import (
    QueueResult,
    ReviewHold,
    enqueue_review,
    queue_payment,
    record_processed,
    record_rejection,
    review_hold,
    supersede_original,
)
from acme.payments.revisions import OriginalPayment, RevisionAction, RevisionKind, resolve_revision
from acme.payments.triggers import (
    RunActivity,
    end_of_day_due,
    idle_batch_due,
    load_runs_snapshot,
    next_batch_time,
    payable_count,
)

__all__ = [
    "BatchAlreadyRunning",
    "BatchResult",
    "InvalidBatchRequest",
    "OriginalPayment",
    "QueueResult",
    "ReviewHold",
    "RevisionAction",
    "RevisionKind",
    "RowResult",
    "RunActivity",
    "end_of_day_due",
    "enqueue_review",
    "idle_batch_due",
    "immediate_scope",
    "is_batch_running",
    "load_runs_snapshot",
    "next_batch_time",
    "pay_now_if_immediate",
    "payable_count",
    "queue_payment",
    "record_processed",
    "record_rejection",
    "recover_interrupted_batch",
    "resolve_revision",
    "resume_payment_failure",
    "review_hold",
    "run_batch",
    "subscribe",
    "supersede_original",
]
