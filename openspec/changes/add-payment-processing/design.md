# Design

## Context

See proposal.md (Why). The repo has no code yet. This change depends on add-project-foundation for:
- the Pydantic models
- the settings object
- the `acme.db` schema: `payment_queue`, `payment_batches`, `payments`, `processed_invoices`, `invoice_runs`, `audit_log`
- the audit logger

Callers come from three other changes:
- add-agent-workflow: the Disposition node and the CLI
- add-backend-api: the endpoints and APScheduler jobs
- add-ipa-web-app: the pages, which call those endpoints

The executor must behave the same whether the CLI or the web server calls it. Both run in one local process against one SQLite file.

## Goals / Non-Goals

**Goals:**
- Use one module, `acme.payments`, for every money-moving path.
- Make the money rules unit-testable without a clock, a scheduler, or a graph.
- Give add-backend-api enough to translate executor results into the HTTP codes the spec requires (202, 409).

**Non-Goals:**
- Scheduling: the APScheduler setup and the polling loop belong to add-backend-api.
- Pausing the graph for review: the `interrupt()` call belongs to add-agent-workflow. This change only records the hold.
- Validation or approval of the revision itself. Those decisions arrive as inputs.

## Decisions

1. **Module split.** The package is `backend/src/acme/payments/`, with one module per concern:
   - `mock_bank.py` holds the README `mock_payment` verbatim, plus an injectable failure hook for tests.
   - `queue.py` holds the disposition tools: `queue_payment`, `supersede_original`, `record_rejection`, `enqueue_review`.
   - `revisions.py` holds `resolve_revision(original_state, revision_total) -> RevisionAction`, a pure function returning one of `REPLACE`, `DELTA(amount)`, `CREDIT_HOLD(overpaid)`, `REVISED_NO_PAYMENT`, or `WAIT_FOR_PAYMENT`.
   - `triggers.py` holds pure functions `next_batch_time(now, settings)`, `end_of_day_due(now, last_eod_run, settings)`, and `idle_batch_due(now, runs_snapshot, queue_count, batch_running, settings)`.
   - `executor.py` holds `run_batch(trigger, released_by, ids=None) -> BatchResult`, which raises `BatchAlreadyRunning` when the lock is held, plus `recover_interrupted_batch()` and `resume_payment_failure(run_id, approve)`.

   These names are the public contract; `add-agent-workflow` (CLI, disposition, `resume_review`) and `add-backend-api` (endpoints, scheduler, lifespan) call nothing else.

   *Alternative:* a single service class. It was rejected because pure trigger and revision functions keep the tests trivial and keep the scheduler choice out of this module.

2. **The lock is a process-level `threading.Lock` plus a DB guard.** `run_batch` acquires the lock non-blocking and, if the lock is already held, raises `BatchAlreadyRunning`, which the API maps to 409 and the scheduler treats as "skip this tick". Inside the lock, the selected rows move from `queued`/`failed` to `paying` in one SQLite transaction (`BEGIN IMMEDIATE`). A stale `paying` row left by a crash is handled by `recover_interrupted_batch()` at startup: paid if its key is in `payments`, otherwise back to `queued` with `last_error="interrupted"` and no attempt counted.

   *Alternative:* a DB-only lock row. It was rejected for an MVP that runs in one process. The `paying` status still guards against a second process.

3. **Idempotency is enforced by the database.** `payments.idempotency_key` is UNIQUE. The key is `f"{vendor}|{invoice_number}|{revision}"`, and delta rows append `|delta`. A pre-check skips rows whose key already exists, and the UNIQUE constraint backstops any race. Vendor is normalized (trimmed and case-folded) before it is used in the key. This prevents duplicates; actual duplicate detection is owned by invoice-validation.

4. **The amount comes from the queue row, not the invoice.** `mock_payment(vendor, amount_usd)` uses the row's amount. That way a delta row pays only the delta, and a replacement row pays the full revision total.

5. **Revision handling happens in two places.**
   - When the workflow detects a `REVISION` finding, it calls `supersede_original` at Disposition time **regardless of the revision's outcome**. That function cancels the original's queued row in the same transaction. For a paid original it does nothing, because a paid original stays Paid.
   - `queue_payment` then consults `resolve_revision` to choose the row kind and amount, or to hold for credit.

   `WAIT_FOR_PAYMENT` is handled by acquiring the batch lock before reading the original's payment state. Disposition waits at most for the in-flight batch, which is short with `mock_payment`.

6. **Escalation to Elevated Review** after `PAYMENT_MAX_ATTEMPTS` failures sets the row to `cancelled` with `last_error` kept, and calls `enqueue_review(run_id, reason="payment failed 3 times: …")`. A reviewer's Approve requeues it and Reject closes it, through `resume_payment_failure` (see the spec).

7. **The rejection log** is the run's `final_status` and `decided_by` in `invoice_runs`, plus an `audit_log` event `rejection.recorded` whose payload holds the rationale, rules, and findings. No separate table is added, so the schema owned by data-model is unchanged.

8. **Time is injected.** Every trigger and executor function takes `now` as an argument or reads it from a `clock` callable, and the timezone is applied with `zoneinfo`. Tests use fixed datetimes.

## Risks / Trade-offs

- [The in-process lock does not protect the CLI and the web server running batches at the same time] → The `paying` status transition under `BEGIN IMMEDIATE` and the UNIQUE idempotency key still prevent double payment. This is documented as the single-process assumption.
- [Disposition waits on the batch lock (`WAIT_FOR_PAYMENT`)] → `mock_payment` is instantaneous. The wait uses a timeout (default 30 s), and on timeout the revision is held for review rather than guessed.
- [Float rounding on deltas] → Amounts are handled as `Decimal` and quantized to cents before they are stored or compared.
- [The idle check relies on accurate run stages] → It reads the `invoice_runs.stage`/`status` that agent-workflow writes. Stale rows from a crashed run would block the idle trigger, so agent-workflow's `recover_orphaned_runs()` handles them at startup (the API re-enqueues them).

## Migration Plan

The project is greenfield, so there is nothing to migrate. Rollback means removing the module, because the tables belong to data-model.

## Open Questions

- Should the payment ID format be `PAY-000123` or the batch-scoped `B-0142-03`? This is display-only and doesn't change the specs.

## Implementation notes

- **`processed_invoices` writer lives here, as an explicit tool.** `record_processed(run_id, invoice, outcome)` (in `acme.payments.queue`) writes the `processed_invoices` row with `vendor = ctx.vendor_key(vendor_name)` and `content_hash(invoice)`, and fills `invoice_runs.invoice_number`, `vendor`, and `total_usd`. It is *not* called implicitly by `queue_payment`/`record_rejection` (`record_rejection` has no invoice, and EXTRACTION_FAILED runs have none), so add-agent-workflow's Disposition node calls it first for every outcome that has a canonical invoice, then `supersede_original` (if REVISION), then the outcome tool. The first run to claim a (vendor, number, revision) keeps it (a DUPLICATE copy does not overwrite the original); the same run re-recording after a review updates its outcome.
- **Signatures.** `queue_payment(run_id, invoice, decision) -> QueueResult(action="queued"|"revised"|"held", row_id, kind, amount, reason)`; `supersede_original(revision_invoice, revision_run_id=None) -> list[run_id]`; `record_rejection(run_id, decision, findings) -> "Rejected"|"Duplicate"`; `enqueue_review(run_id, reason, kind, details=None)` with kind `warning`/`credit`/`payment_failure`; `review_hold(run_id) -> ReviewHold(kind, reason, details) | None` (so `resume_review` can dispatch payment-failure holds); `run_batch(trigger, released_by=None, ids=None) -> BatchResult`; `resume_payment_failure(run_id, approve, reviewer=None, rationale=None) -> new row id | None`; `recover_interrupted_batch() -> {"paid", "requeued"}`. Every disposition tool takes an optional `conn`.
- **Hold storage.** No schema change: the hold kind/reason/details are the latest `review.enqueued` audit event; the rejection log is the `rejection.recorded` event (design D7).
- **Run status vocabulary written here.** Queued: `status`/`stage` = `Queued for payment` (final_status NULL). Hold: `Awaiting review`. Resolved (Paid, Revised, Rejected, Duplicate, Superseded): `status`/`stage` = `Resolved`, `completed_at` set. The idle trigger treats a run as processing when its stage is Uploaded/Extracting/Validating/Deciding or its status is one of those or `Resuming`; `load_runs_snapshot` uses each run's latest `audit_log` time as its last activity.
- **Revisions.** The amount already paid is read fresh from the `payments` ledger under the batch lock, summed across all earlier revisions (delta rows included), so R2 after a paid R0 + delta R1 pays only the remaining difference. (Validation's `RevisionContext.paid_amount` only sums the immediately preceding revision's keys; noted, not changed.) `supersede_original` also waits on the batch lock, so an original whose payment fails mid-batch is still superseded when its revision is rejected. On REPLACE, `queue_payment` re-supersedes any leftover original row. A lock timeout (`PAYMENT_LOCK_TIMEOUT_S`) holds the revision for review (`warning`).
- **Executor details.** Batch IDs are `B-0001` (sequential), payment IDs `PAY-000001`. Every `run_batch` call writes a `payment_batches` record, even with nothing payable (count 0). `count`/`total_usd` cover new payments only; rows whose key was already in the ledger are marked paid as `already_paid`. Per-row results are in the `batch.finished` audit event (run_id NULL). `InvalidBatchRequest` (a `ValueError`) covers bad triggers, `released_by` outside 1–50 trimmed characters, and `pay_selected`/`pay_now` without ids. `mock_payment` is called between transactions, so a crash after the bank call and before the ledger write would be retried after recovery (inherent to the mock; acceptable for the MVP).
- **Events.** `acme.payments.events.subscribe(listener)` receives `payment.queued`, `payment.cancelled`, `batch.started`, `payment.created`, `batch.finished` for add-backend-api's SSE bus (task 7.2) without threading callbacks through the graph.
- **Test hook.** `mock_bank.fail_next(n, error)` / `mock_bank.reset()`; the README function body is otherwise verbatim.
