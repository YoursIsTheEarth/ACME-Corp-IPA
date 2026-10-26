## MODIFIED Requirements

### Requirement: Payment queue view (F40)
`GET /api/payment-queue` SHALL return the rows with status `queued`, `paying`, or `failed`. Each row SHALL include invoice number, vendor, amount in USD, kind (full, replacement, delta), approver, queued time, status, attempts, and last error. The response SHALL also give the queued count and total and the payment mode: whether payment delay is on, the next scheduled end-of-day batch time with its timezone (null when none is scheduled), and whether pay when the Invoice Queue is empty is on.

#### Scenario: Queue after a batch upload
- **WHEN** payment delay is on and end of day is turned on with the default time and timezone, `invoice_1001.txt` and `invoice_1006.csv` have been approved, and no batch has run
- **THEN** the payment queue shows 2 rows of kind full, a queued total of $7,750.00, delay on, and the next end-of-day batch time in America/Chicago

#### Scenario: Immediate mode
- **WHEN** payment delay is off
- **THEN** the response reports delay off and a null next batch time, and lists only rows waiting on a running batch or failed

#### Scenario: Revision replaces a queued row
- **WHEN** payment delay is on and `invoice_1004_revised.json` is approved while `invoice_1004.json` is queued
- **THEN** the payment queue no longer lists the 1004 original
- **AND** it lists the revision as kind replacement for $5,940.00

### Requirement: Scheduled payment batches (F38)
The service SHALL take its schedule from the admin settings. With delay on and pay at end of day on, it SHALL run a batch of everything queued daily at the admin time and timezone (default 5:00 PM America/Chicago) with trigger `end_of_day`. With delay on and pay when the Invoice Queue is empty on, it SHALL run one with trigger `idle` once no invoice has been Uploaded, Extracting, Validating, or Deciding for `PAYMENT_IDLE_DELAY_S` (default 60 seconds) and the queue is not empty; Awaiting review SHALL NOT block it. With delay off, it SHALL start an `immediate` batch whenever rows are payable under the immediate scope and no batch is running. All of these record released by `System`. Saving admin settings SHALL reschedule without a restart.

#### Scenario: Idle trigger waits for the whole upload
- **WHEN** payment delay is on and 3 files are uploaded together
- **THEN** no batch runs until all 3 have left processing and 60 seconds have passed with nothing processing
- **AND** then one `idle` batch pays every queued row

#### Scenario: Held invoice does not block idle
- **WHEN** payment delay is on, the only unresolved invoice is Awaiting review, and payments are queued
- **THEN** the idle batch still runs after the delay

#### Scenario: Idle trigger disabled
- **WHEN** payment delay is on and pay when the Invoice Queue is empty is off
- **THEN** no idle batch runs, and the payment queue view reports it as off

#### Scenario: End-of-day time rescheduled on save
- **WHEN** delay and end of day are on and an admin changes the time from 17:00 to 15:00 America/Chicago
- **THEN** without a restart, the next `end_of_day` batch runs at 3:00 PM Central and none runs at 5:00 PM

#### Scenario: Batch trigger collides with a running batch
- **WHEN** the end-of-day time arrives while a manual batch is running
- **THEN** no second batch runs concurrently
- **AND** rows still queued afterward are picked up by the next trigger

### Requirement: Live event stream (F29, P1)
`GET /api/events` SHALL be a Server-Sent Events stream. It SHALL send `invoice.created`, `invoice.stage_changed`, `invoice.resolved`, `payment.queued`, `payment.cancelled`, `batch.started`, `batch.finished`, `payment.created`, and `settings.updated`. Each event SHALL carry the affected ids and enough data to update a table row; `settings.updated` SHALL carry the full new admin settings. Every connected client SHALL receive every event. The stream SHALL send a keep-alive at least every 15 seconds.

#### Scenario: Upload to resolution
- **WHEN** `invoice_1002.txt` is uploaded and processed while a client is connected
- **THEN** the client receives `invoice.created`, one or more `invoice.stage_changed`, and `invoice.resolved` with final status Rejected, in that order

#### Scenario: Revision swap
- **WHEN** a revision replaces a queued invoice
- **THEN** clients receive `payment.cancelled` for the original and `payment.queued` for the revision

#### Scenario: Batch events
- **WHEN** a batch pays 7 rows
- **THEN** clients receive `batch.started`, seven `payment.created`, and `batch.finished` with count, total, and failed count

#### Scenario: Settings change
- **WHEN** an admin saves new payment timing
- **THEN** every connected client receives `settings.updated` with the saved values

### Requirement: Invoice list views (F23, F24, F25)
`GET /api/invoices` SHALL require `view` to be `queue`, `audit`, or `review`. Any other value SHALL return 422.
- `queue` returns runs not yet resolved: stage Uploaded, Extracting, Validating, Deciding, or Awaiting review.
- `audit` returns resolved runs with final status Paid, Revised, Rejected, Duplicate, Superseded, or Credit confirmed, with decided by and up to 3 key findings.
- `review` returns runs paused for a person, with the held reasons and the AI recommendation.

#### Scenario: Queue view
- **WHEN** a client requests `GET /api/invoices?view=queue` while one invoice is Validating and one is Awaiting review
- **THEN** both are returned
- **AND** each shows file name, invoice number, vendor, amount in USD, stage, status, uploaded time, and time in stage

#### Scenario: Awaiting review shows in two views
- **WHEN** `invoice_1010.txt` is held with `PRICE_VARIANCE`
- **THEN** it appears in both `view=queue` and `view=review`
- **AND** the review entry includes the warning findings, the AI recommendation with its one-line rationale, and the time waiting

#### Scenario: Audit view filters
- **WHEN** a client requests `view=audit` with a status filter of `Rejected`, a date range, and search text `1002`
- **THEN** only resolved runs matching all three filters are returned

#### Scenario: Revised in audit view
- **WHEN** a client requests `view=audit` with a status filter of `Revised` after a paid invoice's revision resolves
- **THEN** the revision is returned with final status Revised

#### Scenario: Unknown view
- **WHEN** a client requests `GET /api/invoices?view=other`
- **THEN** the response is 422

## ADDED Requirements

### Requirement: Read admin settings
`GET /api/admin/settings` SHALL return the payment timing: `delay_payments`, `pay_at_end_of_day`, `end_of_day_time` (24-hour `HH:MM`), `end_of_day_timezone` (IANA name), `pay_when_queue_empty`, plus `updated_by` and `updated_at` of the last save (null if never saved). Unsaved values SHALL be reported with their defaults.

#### Scenario: Defaults
- **WHEN** no admin settings were ever saved
- **THEN** the response is `delay_payments` true, `pay_at_end_of_day` false, `end_of_day_time` "17:00", `end_of_day_timezone` "America/Chicago", `pay_when_queue_empty` true, and `updated_by` null

### Requirement: Update admin settings
`PUT /api/admin/settings` SHALL take all five settings and a required `updated_by`, save them, apply them without a restart, and return the saved settings. It SHALL return 422, saving nothing, when `updated_by` after trimming is empty or longer than 50 characters, `end_of_day_time` is not a valid `HH:MM` time, or `end_of_day_timezone` is not a known IANA timezone.

#### Scenario: Turn on end-of-day payments
- **WHEN** a client puts `pay_at_end_of_day` true with the other defaults and `updated_by` "Dana"
- **THEN** the response is 200 with the saved settings and `updated_by` "Dana", and a later GET returns the same values

#### Scenario: Unknown timezone
- **WHEN** a client puts `end_of_day_timezone` "Mars/Olympus"
- **THEN** the response is 422 naming the timezone field and the stored settings are unchanged

#### Scenario: Bad time
- **WHEN** a client puts `end_of_day_time` "25:00" or "5pm"
- **THEN** the response is 422 naming the time field

#### Scenario: Missing name
- **WHEN** a client puts valid settings with `updated_by` "   "
- **THEN** the response is 422 and nothing is saved

### Requirement: Admin settings changes are audited
Every successful settings save SHALL write one audit log entry with the name of who saved it, the time, and the old and new value of every setting that changed. Saving identical values SHALL still be recorded.

#### Scenario: Audit entry for a change
- **WHEN** "Dana" changes `end_of_day_time` from "17:00" to "15:00"
- **THEN** the audit log has a settings entry by "Dana" showing `end_of_day_time` old "17:00" and new "15:00"
