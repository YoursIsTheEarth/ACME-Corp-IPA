# Spec Delta

## Purpose

Defines the HTTP contract of the ACME Corp IPA backend. The web app uses it to upload invoices, watch processing, decide held invoices, release payments, and read audit and payment history. It runs the same pipeline as the CLI.

## ADDED Requirements

### Requirement: Invoice upload intake (F27)
`POST /api/invoices` SHALL accept a multipart upload of one or more files. Each file SHALL be judged on its own. A file is accepted only when its extension is .pdf, .txt, .csv, .json, .xml, or .eml, it is not empty, and it is 10 MB or less. Each accepted file SHALL be stored, recorded as a new invoice run with status Uploaded, and queued for processing. The response SHALL be 202 within 1 second, with `id`, `file_name`, and `status` for every file.

#### Scenario: Multi-file upload accepted
- **WHEN** a client posts `invoice_1001.txt` and `invoice_1006.csv` in one request
- **THEN** the response is 202 within 1 second
- **AND** it lists both files, each with an `id`, its `file_name`, and status `Uploaded`

#### Scenario: Mixed valid and invalid files
- **WHEN** a client posts `invoice_1001.txt`, `notes.docx`, an empty `blank.txt`, and an 11 MB `big.pdf` together
- **THEN** the response is 202
- **AND** only `invoice_1001.txt` gets an `id` and status `Uploaded`
- **AND** the other three are listed with status `rejected` and an error naming the reason: unsupported type, empty file, or over 10 MB
- **AND** no invoice run is created for the three refused files

#### Scenario: Request with no files
- **WHEN** a client posts to `/api/invoices` with no file parts
- **THEN** the response is 422

### Requirement: Same pipeline as the CLI (F27)
Every accepted upload SHALL be processed in the background through the same agent workflow the CLI uses. The same file under the same provider SHALL reach the same outcome, findings, and amounts as `python main.py --invoice_path=<file>`. The upload request SHALL NOT wait for processing to finish.

#### Scenario: Parity with the CLI
- **WHEN** `invoice_1002.txt` is uploaded through the API in offline mode
- **THEN** its run ends Rejected with finding `STOCK_EXCEEDED`, the same as the CLI result for that file

#### Scenario: Stage progression is visible
- **WHEN** an uploaded invoice is being processed
- **THEN** successive reads of the queue view show its stage advancing through Uploaded, Extracting, Validating, and Deciding

### Requirement: Invoice list views (F23, F24, F25)
`GET /api/invoices` SHALL require `view` to be `queue`, `audit`, or `review`. Any other value SHALL return 422.
- `queue` returns runs not yet resolved: stage Uploaded, Extracting, Validating, Deciding, or Awaiting review.
- `audit` returns resolved runs with final status Paid, Rejected, Duplicate, Superseded, or Credit confirmed, with decided by and up to 3 key findings.
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

#### Scenario: Unknown view
- **WHEN** a client requests `GET /api/invoices?view=other`
- **THEN** the response is 422

### Requirement: Invoice detail and original file (F30)
`GET /api/invoices/{id}` SHALL return the full record: extracted fields, findings, every decision draft and critique with the provider and model behind each, reviewer decisions, payment or rejection records, and the stage timeline from the audit ledger. `GET /api/invoices/{id}/file` SHALL return the original uploaded bytes with a content type that matches the file. An unknown `id` SHALL return 404 on both.

#### Scenario: Detail of a resolved invoice
- **WHEN** a client requests the detail of a rejected `invoice_1009.json` run
- **THEN** the response includes the findings `MISSING_VENDOR`, `INVALID_QUANTITY`, `MATH_MISMATCH`, and `MISSING_DUE_DATE`
- **AND** it includes the timeline entries for every stage that ran

#### Scenario: Original file download
- **WHEN** a client requests `GET /api/invoices/{id}/file` for an uploaded PDF
- **THEN** the response body equals the uploaded bytes and the content type is `application/pdf`

#### Scenario: Unknown invoice
- **WHEN** a client requests `GET /api/invoices/does-not-exist`
- **THEN** the response is 404

### Requirement: Human review resume (F17, F28)
`POST /api/invoices/{id}/review` SHALL take `decision` (`approve` or `reject`), `rationale`, and `reviewer`. It SHALL resume the paused run with that decision and record it in `review_decisions`. On approve, the invoice is added to the payment queue; on reject, it goes to the rejection log.

#### Scenario: Approve a held invoice
- **WHEN** a reviewer posts `decision=approve`, reviewer `Dana`, and a rationale of 15 or more characters for an invoice Awaiting review
- **THEN** the response is 200
- **AND** the invoice leaves `view=review` and `view=queue`
- **AND** a `payment_queue` row with status `queued` exists for it
- **AND** its audit timeline records Dana as the decider with the rationale

#### Scenario: Reject a held invoice
- **WHEN** a reviewer posts `decision=reject` with a valid name and rationale
- **THEN** the invoice resolves as Rejected in `view=audit` and nothing is queued for payment

### Requirement: Review input validation (F25)
The review endpoint SHALL trim the reviewer name and return 422 when it is empty or longer than 50 characters. It SHALL return 422 when the rationale has fewer than 15 characters after trimming, or when `decision` is neither `approve` nor `reject`. A 422 SHALL leave the invoice unchanged.

#### Scenario: Name of only spaces
- **WHEN** a reviewer posts a reviewer name of only spaces
- **THEN** the response is 422 and the invoice stays Awaiting review

#### Scenario: Name too long
- **WHEN** a reviewer posts a 51-character reviewer name
- **THEN** the response is 422

#### Scenario: Name padded with spaces
- **WHEN** a reviewer posts `"  Dana  "`
- **THEN** the decision is stored with reviewer `Dana`

#### Scenario: Short rationale
- **WHEN** a reviewer posts a 14-character rationale
- **THEN** the response is 422

### Requirement: Stale review conflict (F25)
The review endpoint SHALL return 409 when the invoice is not Awaiting review, including when another reviewer already decided it. The invoice's state SHALL NOT change. Only one of two concurrent decisions on the same invoice SHALL succeed.

#### Scenario: Second reviewer loses
- **WHEN** two reviewers post decisions for the same held invoice at nearly the same time
- **THEN** exactly one gets 200 and the other gets 409
- **AND** one `review_decisions` row exists

#### Scenario: Review of a processing invoice
- **WHEN** a client posts a review for an invoice that is still Validating
- **THEN** the response is 409

### Requirement: Credit or refund confirmation (F10, F25)
For a run held because a revision lowers the total of a paid invoice, the review endpoint SHALL treat `approve` as Credit confirmed and `reject` as Reject revision. Neither SHALL queue a payment. The review view SHALL show the amount overpaid for these runs.

#### Scenario: Credit confirmed
- **WHEN** a reviewer approves a lower-total revision of a paid invoice, with a rationale recording the vendor's credit note and its amount
- **THEN** the run resolves with final status Credit confirmed
- **AND** no `payment_queue` row is created

### Requirement: Payment-failure hold decision (F16, F25)
For a run held because its payment failed `PAYMENT_MAX_ATTEMPTS` times, the review view SHALL show the reason "Payment failed" with the last error. `approve` SHALL requeue the payment and `reject` SHALL resolve the run as Rejected, per `payment-processing`.

#### Scenario: Requeue after failures
- **WHEN** a reviewer approves an invoice held after 3 failed payments
- **THEN** the response is 200 and the invoice appears in `/api/payment-queue` as `queued`

### Requirement: Payment queue view (F40)
`GET /api/payment-queue` SHALL return the rows with status `queued`, `paying`, or `failed`. Each row SHALL include invoice number, vendor, amount in USD, kind (full, replacement, delta), approver, queued time, status, attempts, and last error. The response SHALL also give the queued count and total, the next scheduled batch time in America/Chicago, and whether auto-pay on idle is on.

#### Scenario: Queue after a batch upload
- **WHEN** `invoice_1001.txt` and `invoice_1006.csv` have been approved and no batch has run
- **THEN** the payment queue shows 2 rows of kind full, a queued total of $7,750.00, and the next end-of-day batch time

#### Scenario: Revision replaces a queued row
- **WHEN** `invoice_1004_revised.json` is approved while `invoice_1004.json` is queued
- **THEN** the payment queue no longer lists the 1004 original
- **AND** it lists the revision as kind replacement for $5,940.00

### Requirement: Payment batch execution (F16, F38, F40)
`POST /api/payment-queue/execute` SHALL take optional `ids` and required `released_by`. With `ids` omitted it starts a Pay all batch; with one id, a Pay now batch; with several, a Pay selected batch. It SHALL return 202 with the `batch_id`, record the trigger and `released_by`, and pay only rows that are still queued or failed.

#### Scenario: Pay all
- **WHEN** a person posts with no `ids` and `released_by` `Dana`
- **THEN** the response is 202 with a `batch_id`
- **AND** the `payment_batches` record has trigger `pay_all` and released_by `Dana`

#### Scenario: Pay selected
- **WHEN** a person posts `ids` for 2 of 5 queued rows
- **THEN** only those 2 rows are paid
- **AND** the batch trigger is `pay_selected`
- **AND** the other 3 stay queued

#### Scenario: Pay now
- **WHEN** a person posts a single id
- **THEN** the batch trigger is `pay_now` and only that row is paid

### Requirement: Payment execution input validation and conflict (F40)
The execute endpoint SHALL return 422 when `released_by`, after trimming, is empty or longer than 50 characters. It SHALL return 409 when a batch is already running, and the second request SHALL start no batch. Ids that are not queued or failed SHALL be skipped and reported in the batch results.

#### Scenario: Concurrent Pay all
- **WHEN** two Pay all requests arrive while the first batch is still running
- **THEN** the second gets 409
- **AND** each queued row is paid exactly once

#### Scenario: Missing name
- **WHEN** a person posts with `released_by` empty
- **THEN** the response is 422 and no batch starts

### Requirement: Payments and batch history (F26)
`GET /api/payments` SHALL return paid invoices filtered by date and vendor. Each row SHALL include payment ID, invoice number, vendor, amount paid in USD, original amount and currency when not USD, revision delta label when applicable, approver, paid time, idempotency key, batch ID and trigger, and released by. The response SHALL include the total paid for the filter. `GET /api/payment-batches` SHALL return batch history: trigger, released by, count, total, and failed count.

#### Scenario: EUR invoice payment
- **WHEN** `invoice_1014.xml` has been paid
- **THEN** its payments row shows the USD amount and the original EUR 4,125.00

#### Scenario: Scheduled batch released by System
- **WHEN** a batch was started by the end-of-day or idle trigger
- **THEN** its rows show released by `System` and the matching trigger

### Requirement: Stats for tiles and badges (F21, F31)
`GET /api/stats` SHALL return counts for invoices in the queue, awaiting review, and in the payment queue, plus paid today and rejected today, and an `llm` object with the active provider and model per agent role (from `llm-provider`'s active-model report) for the sidebar footer. P1: it SHALL also return dollars queued, dollars paid, dollars blocked, and duplicates caught.

#### Scenario: Badge counts
- **WHEN** 3 invoices are processing, 1 is awaiting review, and 2 payments are queued
- **THEN** `/api/stats` returns an in-queue count of 4, an awaiting-review count of 1, and a payment-queue count of 2

#### Scenario: Active model reported
- **WHEN** the server runs with `LLM_PROVIDER=claude` and `CLAUDE_MODEL=claude-sonnet-5-5`
- **THEN** `/api/stats` returns `llm.provider` `claude` and `llm.model` `claude-sonnet-5-5`

### Requirement: Scheduled payment batches (F38)
The service SHALL run a batch of everything queued daily at `PAYMENT_BATCH_TIME`, default 5:00 PM America/Chicago, with trigger `end_of_day`. It SHALL also run one with trigger `idle` once no invoice has been Uploaded, Extracting, Validating, or Deciding for `PAYMENT_IDLE_DELAY_S`, default 60 seconds, and the queue is not empty. Awaiting review SHALL NOT block the idle trigger. `PAYMENT_AUTO_IDLE=false` disables the idle trigger. Both triggers record released by `System`.

#### Scenario: Idle trigger waits for the whole upload
- **WHEN** 3 files are uploaded together
- **THEN** no batch runs until all 3 have left processing and 60 seconds have passed with nothing processing
- **AND** then one `idle` batch pays every queued row

#### Scenario: Held invoice does not block idle
- **WHEN** the only unresolved invoice is Awaiting review and payments are queued
- **THEN** the idle batch still runs after the delay

#### Scenario: Idle trigger disabled
- **WHEN** `PAYMENT_AUTO_IDLE=false`
- **THEN** no idle batch runs, and the payment queue view reports auto-pay on idle as off

#### Scenario: Batch trigger collides with a running batch
- **WHEN** the end-of-day time arrives while a manual batch is running
- **THEN** no second batch runs concurrently
- **AND** rows still queued afterward are picked up by the next trigger

### Requirement: Restart durability (F28)
After a server restart, the service SHALL keep every invoice Awaiting review decidable via the review endpoint. It SHALL keep queued and failed payments in the queue, and resume processing of invoices that were mid-pipeline. Rows left in `paying` SHALL be re-checked against the payments ledger: a row whose idempotency key is already paid becomes paid, and any other row returns to queued. No payment SHALL be lost or made twice.

#### Scenario: Review after restart
- **WHEN** `invoice_1010.txt` is Awaiting review, the server restarts, and a reviewer approves it
- **THEN** the original run resumes and the invoice is queued for payment

#### Scenario: Crash mid-batch
- **WHEN** the server stops while a batch is paying 3 rows and 1 had already been paid
- **THEN** after restart that row is paid, the other 2 are queued, and the next batch pays only those 2

### Requirement: Polling contract (F29)
Every list, detail, stats, and payment-queue endpoint SHALL return the full current state, not a diff, so a client that polls every 3 seconds sees the same data an SSE client would. Each list response SHALL include a `server_time` field.

#### Scenario: Polling sees a stage change
- **WHEN** a client polls `view=queue` every 3 seconds while an invoice moves from Extracting to Validating
- **THEN** a poll within 3 seconds of the change shows stage Validating

### Requirement: Live event stream (F29, P1)
`GET /api/events` SHALL be a Server-Sent Events stream. It SHALL send `invoice.created`, `invoice.stage_changed`, `invoice.resolved`, `payment.queued`, `payment.cancelled`, `batch.started`, `batch.finished`, and `payment.created`. Each event SHALL carry the affected ids and enough data to update a table row. Every connected client SHALL receive every event. The stream SHALL send a keep-alive at least every 15 seconds.

#### Scenario: Upload to resolution
- **WHEN** `invoice_1002.txt` is uploaded and processed while a client is connected
- **THEN** the client receives `invoice.created`, one or more `invoice.stage_changed`, and `invoice.resolved` with final status Rejected, in that order

#### Scenario: Revision swap
- **WHEN** a revision replaces a queued invoice
- **THEN** clients receive `payment.cancelled` for the original and `payment.queued` for the revision

#### Scenario: Batch events
- **WHEN** a batch pays 7 rows
- **THEN** clients receive `batch.started`, seven `payment.created`, and `batch.finished` with count, total, and failed count

### Requirement: CSV export (F35, P2)
`GET /api/invoices.csv` SHALL return the audit view and `GET /api/payments.csv` the payments view as `text/csv`, honoring the same filters as their JSON endpoints, with a header row.

#### Scenario: Filtered payments export
- **WHEN** a client requests `/api/payments.csv` with a vendor filter
- **THEN** the CSV contains a header row and exactly the rows `/api/payments` returns for that filter

### Requirement: Cross-origin and access policy
The service SHALL allow cross-origin requests only from the configured Angular dev server origin, default `http://localhost:4200`. It SHALL require no login. Request bodies SHALL be validated, and errors SHALL return JSON with a readable message.

#### Scenario: Disallowed origin
- **WHEN** a browser at `http://evil.example` calls the API
- **THEN** the response carries no CORS allow header for that origin

#### Scenario: Allowed origin
- **WHEN** the Angular dev server at `http://localhost:4200` calls the API
- **THEN** the response allows that origin
