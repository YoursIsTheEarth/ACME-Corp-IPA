# Tasks

All tasks are P0 - MVP (F16, F17 rejection log, F38, F39). This change has no P1 or P2 items. Its P1 consumers (live batch toasts F29, home tiles F31) belong to other changes.

## 1. Module scaffolding

- [x] 1.1 Create `backend/src/acme/payments/` with `__init__.py`, `mock_bank.py`, `queue.py`, `revisions.py`, `triggers.py`, `executor.py`, and verify `python -c "import acme.payments"` succeeds
- [x] 1.2 Read `PAYMENT_BATCH_TIME`, `PAYMENT_TZ`, `PAYMENT_IDLE_DELAY_S`, `PAYMENT_AUTO_IDLE`, `PAYMENT_MAX_ATTEMPTS`, and `PAYMENT_LOCK_TIMEOUT_S` from the foundation settings catalog, and verify a settings unit test reads the defaults
- [x] 1.3 Implement `mock_bank.mock_payment(vendor, amount)` verbatim from the README, plus a test-only failure hook, and verify a unit test can force a failure

## 2. Pure decision logic

- [x] 2.1 Implement `revisions.resolve_revision` for the 5 cases in "Revisions and the queue" (unpaid → REPLACE, paid higher → DELTA, paid lower → CREDIT_HOLD, paid same → REVISED_NO_PAYMENT, paying → WAIT_FOR_PAYMENT) using `Decimal`, and verify that `backend/tests/payments/test_revisions.py` covers each case with INV-1004-based totals
- [x] 2.2 Implement `triggers.next_batch_time` and `end_of_day_due` with `zoneinfo`, and verify tests for before and after 5:00 PM CT and a DST boundary
- [x] 2.3 Implement `triggers.idle_batch_due`, and verify tests for multi-file upload, Awaiting review not blocking, `PAYMENT_AUTO_IDLE=false`, an empty queue, and a running batch

## 3. Disposition tools

- [x] 3.1 Implement `queue_payment(run_id, invoice, decision)` writing a `payment_queue` row with the kind and amount from `resolve_revision`, and verify the tests for INV-1001 (full), R1 (replacement $5,940), and the delta case
- [x] 3.2 Implement `supersede_original(revision_invoice)`, which sets the original's `final_status` to Superseded and cancels its queued row in one transaction, plus an `audit_log` event. Verify tests for the queued, held, and rejected originals, and for the paid original being left unchanged
- [x] 3.3 Implement `record_rejection(run_id, decision, findings)`, which sets `final_status` to Rejected or Duplicate and writes a `rejection.recorded` audit event. Verify tests for INV-1002 and invoice_1011.txt
- [x] 3.4 Implement `enqueue_review(run_id, reason, kind)` for warning holds, credit holds, and payment-failure escalation, and verify a test that the run shows as awaiting review with the reason

## 4. Batch executor

- [x] 4.1 Implement the `run_batch` lock, row selection by trigger (all rows, or the given ids), and the `queued`/`failed` → `paying` transition under `BEGIN IMMEDIATE`. Verify that a test with two concurrent calls gets one `BatchAlreadyRunning` and one payment per row
- [x] 4.2 Implement the per-row re-check (still payable, not Superseded, idempotency key unused), the `mock_payment` call, the `payments` ledger write, and the `paid` status. Verify that a test running a batch twice makes zero new payments, and that a cancelled-mid-batch row is skipped
- [x] 4.3 Implement failure handling: mark the row `failed`, increment `attempts`, store `last_error`, and escalate to `enqueue_review` at `PAYMENT_MAX_ATTEMPTS`. Verify a test with 3 forced failures
- [x] 4.4 Write the `payment_batches` record (trigger, released_by validation 1–50 chars trimmed, System for end_of_day and idle, count, total, failed_count, per-row results), and verify tests for the Pay all record and for a refused blank or 51-char name
- [x] 4.5 Implement `recover_interrupted_batch()` (paid if the key is in `payments`, else back to `queued` with "interrupted" and no attempt counted), and verify the crash-mid-batch test (3 paying, 1 already paid → 1 paid, 2 queued)
- [x] 4.7 Implement `resume_payment_failure(run_id, approve)` (approve requeues with 0 attempts and the same key; reject records Rejected), and verify both paths
- [x] 4.6 Handle WAIT_FOR_PAYMENT in Disposition by waiting on the batch lock with a timeout, falling back to a review hold. Verify the mid-batch revision test

## 5. Integration checks

- [x] 5.1 Write `backend/tests/payments/test_revision_scenarios.py` covering the 8 spec scenarios: queued revision, paid higher, paid lower, paid same, queued revision fails a rule, idle trigger, concurrent Pay all, and payment failure. Verify `pytest backend/tests/payments` passes
- [x] 5.2 Document the public API (`run_batch`, the trigger functions, and the disposition tools), plus the single-process assumption, in a module docstring in `acme/payments/__init__.py`, and verify that add-agent-workflow and add-backend-api reference only these entry points
