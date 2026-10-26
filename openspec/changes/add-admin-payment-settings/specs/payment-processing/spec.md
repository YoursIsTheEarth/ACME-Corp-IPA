## MODIFIED Requirements

### Requirement: Approval queues payment instead of paying (F16)
When an invoice's final decision is APPROVE, the system SHALL add one `payment_queue` row with status `queued`, `attempts` 0, `amount_usd`, `vendor`, `invoice_number`, `revision`, `kind` (`full`, `replacement`, or `delta`), and `queued_at`. Approval itself MUST NOT call `mock_payment`; only the executor pays. When payment delay is off, the row SHALL then be paid by an `immediate` batch before the run is reported finished; when delay is on, it SHALL wait for a batch.

#### Scenario: Clean invoice is queued, not paid
- **WHEN** payment delay is on and INV-1001 ($5,000.00) is approved
- **THEN** a `payment_queue` row exists with status `queued`, kind `full`, amount_usd 5000.00
- **AND** no row exists in `payments` for INV-1001 and `mock_payment` has not been called

#### Scenario: Clean invoice is paid at approval when delay is off
- **WHEN** payment delay is off and INV-1001 ($5,000.00) is approved
- **THEN** its run finishes with final status Paid, a `payments` entry for $5,000.00 exists, and the batch that paid it has trigger `immediate` and released_by `System`

#### Scenario: Non-USD invoice is queued in USD
- **WHEN** INV-1014 (EUR 4,125.00) is approved
- **THEN** its queue row's `amount_usd` is the total converted at the configured rate

### Requirement: Batch records (F16, F38)
Every batch SHALL write a `payment_batches` record with `batch_id`, `trigger` (`end_of_day`, `idle`, `immediate`, `pay_all`, `pay_selected`, `pay_now`), `released_by`, `started_at`, `finished_at`, `count`, `total_usd`, and `failed_count`, plus per-row results. `released_by` SHALL be `System` for `end_of_day`, `idle`, and `immediate`, and the supplied name (1 to 50 characters after trimming) otherwise.

#### Scenario: Manual batch records who released it
- **WHEN** a person named "Dana" runs Pay all after the golden run with payment delay on and 7 rows are paid totaling $37,620.00 (EUR at the default 1.08)
- **THEN** a `payment_batches` record has trigger `pay_all`, released_by "Dana", count 7, total_usd 37620.00, failed_count 0

#### Scenario: Immediate batch released by System
- **WHEN** payment delay is off and an approved invoice is paid at approval
- **THEN** the `payment_batches` record has trigger `immediate` and released_by `System`

#### Scenario: Missing release name is refused
- **WHEN** a manual batch is requested with a blank or 51-character `released_by`
- **THEN** the request is refused and no batch starts

### Requirement: Batch scope by trigger (F38)
Batches started by `end_of_day`, `idle`, or `pay_all` SHALL attempt every payable row. Batches started by `pay_selected` or `pay_now` SHALL attempt only the given row IDs that are payable. Batches started by `immediate` SHALL attempt every `queued` row, plus every `failed` row with attempts remaining whose last attempt was at least `PAYMENT_IDLE_DELAY_S` seconds ago.

#### Scenario: Pay selected pays only checked rows
- **WHEN** three rows are queued and Pay selected is run with two of their IDs
- **THEN** only those two rows are paid and the third stays `queued`

#### Scenario: Immediate batch skips a just-failed row
- **WHEN** payment delay is off, a row failed 10 seconds ago, and a new invoice is approved
- **THEN** the `immediate` batch pays the new invoice's row and does not retry the failed row yet

### Requirement: End-of-day trigger decision (F38)
The system SHALL expose a decision that an end-of-day batch is due once per day at the admin end-of-day time (default 17:00) in the admin timezone (default America/Chicago), only when payment delay is on and pay at end of day is on. It SHALL also report the next scheduled batch time for display, or none when no end-of-day batch is scheduled.

#### Scenario: Next batch time
- **WHEN** delay and end of day are on with the defaults and the next batch time is requested at 2:00 PM Central
- **THEN** it reports today at 5:00 PM Central

#### Scenario: After the batch time
- **WHEN** delay and end of day are on with the defaults and it is requested at 6:00 PM Central
- **THEN** it reports tomorrow at 5:00 PM Central

#### Scenario: Custom time and timezone
- **WHEN** delay and end of day are on with time 08:30 and timezone America/New_York, and the next batch time is requested at 9:00 AM Eastern
- **THEN** it reports tomorrow at 8:30 AM Eastern

#### Scenario: No end-of-day batch when delay is off
- **WHEN** payment delay is off, or delay is on and pay at end of day is off
- **THEN** no end-of-day batch is ever due and the next batch time is reported as none

### Requirement: Idle trigger decision (F38)
An idle batch SHALL be due only when payment delay is on, pay when the Invoice Queue is empty is on, the payment queue has at least one payable row, no invoice has been in Uploaded, Extracting, Validating, or Deciding for at least `PAYMENT_IDLE_DELAY_S` seconds (default 60), and no batch is running. Invoices in Awaiting review SHALL NOT block it.

#### Scenario: Multi-file upload does not trigger early
- **WHEN** delay and pay when queue empty are on, 3 files are uploaded, and the first is approved while the others are still Extracting
- **THEN** no idle batch is due until all 3 finish and 60 seconds pass with nothing processing

#### Scenario: Awaiting review does not block
- **WHEN** delay and pay when queue empty are on, the only unresolved invoice is INV-1010 in Awaiting review, a row is queued, and 60 seconds have passed since processing ended
- **THEN** an idle batch is due

#### Scenario: Idle trigger disabled
- **WHEN** pay when the Invoice Queue is empty is off, or payment delay is off
- **THEN** an idle batch is never due

#### Scenario: Empty queue
- **WHEN** the system is idle but no payable rows exist
- **THEN** no idle batch is due

## ADDED Requirements

### Requirement: Payment timing settings
The system SHALL read payment timing from stored admin settings: delay payments (default off), pay at end of day (default on), end-of-day time (default 17:00), end-of-day timezone (default America/Chicago), and pay when the Invoice Queue is empty (default on). Defaults SHALL apply to any value never saved. A saved change SHALL take effect for the next decision without a restart.

#### Scenario: Defaults on a new database
- **WHEN** payment timing is read from a freshly seeded `acme.db`
- **THEN** delay is off, end of day is on at 17:00 America/Chicago, and pay when queue empty is on

#### Scenario: Change applies without restart
- **WHEN** delay is turned on while the system is running and an invoice is approved afterward
- **THEN** that invoice's row stays `queued` and no `immediate` batch runs

### Requirement: Immediate payment waits for a running batch
When payment delay is off and an approved row cannot be paid because another batch is running, the row SHALL stay `queued` and SHALL be paid by an `immediate` batch started as soon as the running batch finishes. No approved row SHALL be left unpaid while delay is off and the queue is otherwise idle.

#### Scenario: Approval during a manual batch
- **WHEN** payment delay is off and INV-1006 is approved while a Pay all batch is running
- **THEN** INV-1006 is not paid by a second concurrent batch
- **AND** once Pay all finishes, an `immediate` batch pays INV-1006

### Requirement: Failed payment retries when delay is off
When payment delay is off, a `failed` row with attempts remaining SHALL be retried by an `immediate` batch once at least `PAYMENT_IDLE_DELAY_S` seconds have passed since its last attempt, and by any manual batch that includes it. After `PAYMENT_MAX_ATTEMPTS` failures it SHALL be held in Elevated Review as with delayed payments.

#### Scenario: Retry after the wait
- **WHEN** payment delay is off and a row's payment fails once
- **THEN** it shows `failed`, is not retried within `PAYMENT_IDLE_DELAY_S` seconds, and is retried by an `immediate` batch after that

#### Scenario: Third failure escalates in immediate mode
- **WHEN** payment delay is off and a row fails on its third attempt
- **THEN** it is no longer payable by batches and the invoice appears in Elevated Review

### Requirement: Switching payment timing
Turning payment delay from on to off SHALL pay every row then payable in one `immediate` batch. Turning it from off to on SHALL pay nothing; rows approved afterward SHALL wait for an end-of-day, idle, or manual batch.

#### Scenario: Delay turned off with rows queued
- **WHEN** 3 rows are queued under delayed payments and delay is turned off
- **THEN** one `immediate` batch pays all 3

#### Scenario: Delay turned on
- **WHEN** delay is turned on with nothing queued and two invoices are then approved
- **THEN** both rows stay `queued` until a batch runs

### Requirement: Revisions under immediate payment
When payment delay is off, an approved original is normally already paid when its revision arrives, so the revision SHALL be handled by the paid-original rules: a higher total queues and immediately pays only the delta, a lower total is held for credit, and the same total is recorded as Revised.

#### Scenario: INV-1004 revision pays the delta
- **WHEN** payment delay is off, INV-1004 is paid $1,890.00 at approval, and invoice_1004_revised.json ($5,940.00) is then approved
- **THEN** INV-1004 stays Paid, a `delta` row for $4,050.00 is paid by an `immediate` batch, and the revision's final status is Revised
