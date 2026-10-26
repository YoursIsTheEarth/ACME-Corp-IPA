# Spec Delta

## Purpose

Moves money for approved invoices only through a queued, batched, idempotent executor. Ensures late revisions replace or top up originals safely, and records every rejection with its reasons so nothing is paid wrongly or twice.

## ADDED Requirements

### Requirement: Approval queues payment instead of paying (F16)
When an invoice's final decision is APPROVE, the system SHALL add one `payment_queue` row with status `queued`, `attempts` 0, `amount_usd`, `vendor`, `invoice_number`, `revision`, `kind` (`full`, `replacement`, or `delta`), and `queued_at`. Approval itself MUST NOT call `mock_payment`.

#### Scenario: Clean invoice is queued, not paid
- **WHEN** INV-1001 ($5,000.00) is approved
- **THEN** a `payment_queue` row exists with status `queued`, kind `full`, amount_usd 5000.00
- **AND** no row exists in `payments` for INV-1001 and `mock_payment` has not been called

#### Scenario: Non-USD invoice is queued in USD
- **WHEN** INV-1014 (EUR 4,125.00) is approved
- **THEN** its queue row's `amount_usd` is the total converted at the configured rate

### Requirement: Rejections are logged with reasons (F17)
When an invoice's final decision is REJECT, the system SHALL record the rejection with the invoice identity, the decision rationale, the rules applied, and every finding (code, severity, message, evidence). It SHALL set the run's `final_status` to Rejected, or to Duplicate when a `DUPLICATE` finding caused the rejection. No payment row is created.

#### Scenario: Stock overrun rejection is logged
- **WHEN** INV-1002 is rejected with a `STOCK_EXCEEDED` finding
- **THEN** the rejection record includes the rationale and the `STOCK_EXCEEDED` finding with its evidence
- **AND** no `payment_queue` row exists for INV-1002

#### Scenario: Duplicate is logged as Duplicate
- **WHEN** invoice_1011.txt is rejected with a `DUPLICATE` finding
- **THEN** its final status is Duplicate and it has no queue or payment row

### Requirement: Single batch at a time (F16)
The system SHALL run at most one payment batch at a time. A request to start a batch while another is running SHALL be refused with a "batch already running" result and SHALL NOT pay any row. Rows in the running batch SHALL have status `paying` and SHALL NOT be selectable by another batch.

#### Scenario: Concurrent Pay all
- **WHEN** two Pay all requests arrive while the first batch is still running
- **THEN** the second request is refused as already running
- **AND** each queued row is paid exactly once

### Requirement: Rows re-checked before payment (F16)
Immediately before paying a row, the executor SHALL confirm the row is still `queued` (or `failed` with attempts remaining), that its invoice is not Superseded, and that its idempotency key (`vendor + invoice_number + revision`, plus a delta suffix for delta rows) has no entry in the `payments` ledger. A row failing any check SHALL be skipped and not paid.

#### Scenario: Cancelled row is skipped
- **WHEN** a row is cancelled after a batch was selected but before it is paid
- **THEN** the executor skips it and `mock_payment` is not called for it

#### Scenario: Idempotency key already used
- **WHEN** a batch reaches a row whose idempotency key already exists in `payments`
- **THEN** nothing is paid for that row and it is marked `paid` with a note that it was already paid

### Requirement: Payment execution and ledger (F16)
For each row that passes the re-check, the executor SHALL call `mock_payment(vendor, amount)` once. On success it SHALL write a `payments` ledger entry (unique `idempotency_key`, vendor, amount_usd, paid_at, batch reference, payment ID). It SHALL then mark the row `paid` and the run's `final_status` Paid, or Revised for delta payments.

#### Scenario: Successful batch pays queued rows
- **WHEN** a batch runs with INV-1001 and INV-1006 queued
- **THEN** `mock_payment` is called once per row and each has a `payments` entry with a payment ID

#### Scenario: Running the batch twice
- **WHEN** a batch completes and a second batch runs immediately after
- **THEN** the second batch makes zero new payments

### Requirement: Failed payments retry then escalate (F16)
If `mock_payment` raises or returns a non-success status, the executor SHALL mark the row `failed`, increment `attempts`, and store `last_error`. Later batches SHALL retry it. When `attempts` reaches `PAYMENT_MAX_ATTEMPTS` (default 3), the row SHALL leave the payment queue and the invoice SHALL be held in Elevated Review with the error as the hold reason.

#### Scenario: Failure is retried next batch
- **WHEN** a row's payment fails once
- **THEN** it shows status `failed` with the error, and the next batch attempts it again

#### Scenario: Third failure escalates
- **WHEN** a row fails on its third attempt
- **THEN** it is no longer payable by batches and the invoice appears in Elevated Review

### Requirement: Batch records (F16, F38)
Every batch SHALL write a `payment_batches` record with `batch_id`, `trigger` (`end_of_day`, `idle`, `pay_all`, `pay_selected`, `pay_now`), `released_by`, `started_at`, `finished_at`, `count`, `total_usd`, and `failed_count`, plus per-row results. `released_by` SHALL be `System` for `end_of_day` and `idle` and the supplied name (1 to 50 characters after trimming) otherwise.

#### Scenario: Manual batch records who released it
- **WHEN** a person named "Dana" runs Pay all after the golden run and 7 rows are paid totaling $37,620.00 (EUR at the default 1.08)
- **THEN** a `payment_batches` record has trigger `pay_all`, released_by "Dana", count 7, total_usd 37620.00, failed_count 0

#### Scenario: Missing release name is refused
- **WHEN** a manual batch is requested with a blank or 51-character `released_by`
- **THEN** the request is refused and no batch starts

### Requirement: Batch scope by trigger (F38)
Batches started by `end_of_day`, `idle`, or `pay_all` SHALL attempt every payable row. Batches started by `pay_selected` or `pay_now` SHALL attempt only the given row IDs that are payable.

#### Scenario: Pay selected pays only checked rows
- **WHEN** three rows are queued and Pay selected is run with two of their IDs
- **THEN** only those two rows are paid and the third stays `queued`

### Requirement: End-of-day trigger decision (F38)
The system SHALL expose a decision that an end-of-day batch is due once per day at `PAYMENT_BATCH_TIME` (default 17:00) in `PAYMENT_TZ` (default America/Chicago). It SHALL also report the next scheduled batch time for display.

#### Scenario: Next batch time
- **WHEN** the next batch time is requested at 2:00 PM Central
- **THEN** it reports today at 5:00 PM Central

#### Scenario: After the batch time
- **WHEN** it is requested at 6:00 PM Central
- **THEN** it reports tomorrow at 5:00 PM Central

### Requirement: Idle trigger decision (F38)
An idle batch SHALL be due only when `PAYMENT_AUTO_IDLE` is true, the payment queue has at least one payable row, no invoice has been in Uploaded, Extracting, Validating, or Deciding for at least `PAYMENT_IDLE_DELAY_S` seconds (default 60), and no batch is running. Invoices in Awaiting review SHALL NOT block it.

#### Scenario: Multi-file upload does not trigger early
- **WHEN** 3 files are uploaded and the first is approved while the others are still Extracting
- **THEN** no idle batch is due until all 3 finish and 60 seconds pass with nothing processing

#### Scenario: Awaiting review does not block
- **WHEN** the only unresolved invoice is INV-1010 in Awaiting review, a row is queued, and 60 seconds have passed since processing ended
- **THEN** an idle batch is due

#### Scenario: Idle trigger disabled
- **WHEN** `PAYMENT_AUTO_IDLE` is false
- **THEN** an idle batch is never due

#### Scenario: Empty queue
- **WHEN** the system is idle but no payable rows exist
- **THEN** no idle batch is due

### Requirement: Revision of an unpaid original replaces it (F39, F10)
When a revision arrives and its original is not yet paid (queued, held for review, or rejected), the system SHALL mark the original Superseded and cancel any queued payment for it before any batch can pay it. If the revision is approved, it SHALL be queued for its full total with kind `replacement`.

#### Scenario: INV-1004 replaced by R1 before the batch
- **WHEN** INV-1004 ($1,890) is queued and invoice_1004_revised.json ($5,940) is approved before a batch runs
- **THEN** INV-1004 is Superseded with `SUPERSEDED_BY_REVISION`, its queue row is `cancelled`, and R1 is queued for $5,940.00 with kind `replacement`
- **AND** the next batch pays $5,940.00 for R1 and nothing for the original

#### Scenario: Revision of a queued invoice fails a rule
- **WHEN** a revision of a queued invoice is rejected or held
- **THEN** the original stays Superseded and unpaid and nothing is queued for either

### Requirement: Revision of a paid original with a higher total pays the delta (F39, F10)
When a revision of a paid invoice has a higher total and is approved, the system SHALL queue only the difference (revision total minus amount already paid) with kind `delta`. Its idempotency key SHALL be distinct from the original's.

#### Scenario: Higher total after payment
- **WHEN** INV-1004 was paid $1,890 and an approved revision totals $2,390
- **THEN** a `delta` row for $500.00 is queued and paid in the next batch

### Requirement: Revision of a paid original with a lower total is held for credit (F39, F10)
When a revision of a paid invoice has a lower total, the system SHALL NOT queue any payment. It SHALL hold the revision in Elevated Review as a credit or refund confirmation, with the overpaid amount as the hold reason.

#### Scenario: Lower total after payment
- **WHEN** INV-1004 was paid $1,890 and a revision totals $1,500
- **THEN** nothing is queued and the revision is held in Elevated Review showing $390.00 overpaid

### Requirement: Revision of a paid original with the same total (F39)
When a revision of a paid invoice has the same total, the system SHALL record it as Revised with no payment due.

#### Scenario: Same total after payment
- **WHEN** INV-1004 was paid $1,890 and a revision totals $1,890
- **THEN** the revision's final status is Revised and nothing is queued

### Requirement: Revision arriving during payment (F39)
When a revision arrives while its original's row is `paying`, the system SHALL wait for that payment to finish. If it succeeds, the revision SHALL be handled as a revision of a paid invoice; if it fails, as a revision of an unpaid invoice.

#### Scenario: Revision lands mid-batch
- **WHEN** a revision of INV-1004 arrives while INV-1004's row is `paying` and that payment then succeeds
- **THEN** the revision is handled as a revision of a paid invoice (delta, credit hold, or Revised)

### Requirement: Payment-failure hold decisions (F16, F25)
An invoice held because its payment failed `PAYMENT_MAX_ATTEMPTS` times SHALL be decidable like any other hold. Approve SHALL requeue it as a new `queued` row with `attempts` 0 and the same kind, amount, and idempotency key. Reject SHALL resolve the run as Rejected, logging the error and the reviewer's rationale, and SHALL queue nothing.

#### Scenario: Approve requeues
- **WHEN** a reviewer approves an invoice held after 3 failed payments
- **THEN** a fresh `queued` row with 0 attempts exists for it and the next batch attempts it once more

#### Scenario: Reject closes it
- **WHEN** a reviewer rejects that hold
- **THEN** the run is Rejected and no queue row is payable

### Requirement: Recovery of an interrupted batch (F28)
`recover_interrupted_batch()` SHALL run at startup of the CLI and the API, before any batch. A row left `paying` SHALL become `paid` if its idempotency key is in `payments`; otherwise it SHALL return to `queued` with `last_error` "interrupted", without counting an attempt.

#### Scenario: Crash mid-batch
- **WHEN** 3 rows are `paying` at startup and 1 of their keys is in `payments`
- **THEN** that row is `paid`, the other 2 are `queued`, and the next batch pays exactly 2
