# Proposal

## Why

The design principle is that "only the Pay node moves money," and today nothing moves money safely. Approved invoices need a payment queue and a batch executor. The queue gives a late revision a chance to replace an invoice before it is paid, and it guarantees that no invoice is paid twice (success metrics: 0 bad payments released, 0 duplicate payments). The other changes depend on this one. The workflow's Disposition node needs somewhere to put approved and rejected invoices, and the CLI and backend API need an executor and trigger logic to call.

## What Changes

- **F16 (P0) Payment queue and batch executor.** APPROVE adds a `payment_queue` row and never pays directly. A batch executor runs one batch at a time under a lock, re-checks each row, enforces the idempotency key (`vendor + invoice_number + revision`), calls the README's `mock_payment(vendor, amount)`, and records each payment in the `payments` ledger. Failed rows retry up to 3 attempts and then move to Elevated Review. Each batch writes a `payment_batches` record.
- **F38 (P0) Batch trigger logic.** Pure, scheduler-agnostic functions decide when a batch is due:
  - End of day at `PAYMENT_BATCH_TIME`, default 5:00 PM America/Chicago.
  - Invoice Queue idle for `PAYMENT_IDLE_DELAY_S`, default 60 s. Invoices in Awaiting review don't block this trigger. `PAYMENT_AUTO_IDLE=false` turns it off.
  - Manual triggers: `pay_all`, `pay_selected`, `pay_now`.

  No scheduler lives here. add-backend-api wires APScheduler, and add-agent-workflow's CLI calls the executor for `--pay` and `python main.py payments run`.
- **F39 (P0) Revisions and the queue.** Disposition helpers apply the "Revisions and the queue" table:
  - **Unpaid original:** the original is marked Superseded and its queued payment cancelled, then the revision is queued for its full total (`kind=replacement`).
  - **Paid original, higher total:** only the delta is queued (`kind=delta`).
  - **Paid original, lower total:** the revision goes to Elevated Review as a credit or refund hold.
  - **Paid original, same total:** recorded as Revised, with no payment due.
  - **Original being paid at that moment:** treated as paid once its payment completes.
- **F17, rejection part (P0).** `record_rejection` writes the reasons and findings for a REJECT to the rejection log. The review hold and graph pause stay in add-agent-workflow.
- Disposition tools for the workflow: `queue_payment`, `supersede_original`, `record_rejection`, `enqueue_review`. `enqueue_review` records the hold reason; add-agent-workflow does the pausing.

## Capabilities

### New Capabilities
- `payment-processing`: covers the payment queue, the batch executor and its idempotency, retry and escalation of failed payments, batch records, the batch trigger decisions, how revisions interact with the queue and paid invoices, and logging of rejections.

### Modified Capabilities
- None. No main specs exist yet.

## Impact

- **New code** in `backend/src/acme/payments/`:
  - `queue.py`: disposition helpers
  - `executor.py`: batch executor and lock
  - `triggers.py`: pure trigger decisions
  - `revisions.py`: revision outcome resolution
  - `mock_bank.py`: the README `mock_payment`
- **Uses tables defined by add-project-foundation (data-model):** `payment_queue`, `payment_batches`, `payments`, `processed_invoices`, `invoice_runs`, `audit_log`. This change specifies how those tables are used, not their schema.
- **Settings** read through the foundation's pydantic-settings: `PAYMENT_BATCH_TIME`, `PAYMENT_IDLE_DELAY_S`, `PAYMENT_AUTO_IDLE`, `PAYMENT_TZ` (default `America/Chicago`), `PAYMENT_MAX_ATTEMPTS` (default 3).
- **Used by:**
  - add-agent-workflow: the Disposition node, plus the CLI's `--pay` and `payments run`
  - add-backend-api: `POST /api/payment-queue/execute`, which returns 409 while a batch is running, and the scheduler jobs
  - add-ipa-web-app: the Payment Queue and Payments pages
- **No new third-party dependencies.** The code uses `zoneinfo` from the standard library and `sqlite3`/the foundation's DB layer.
