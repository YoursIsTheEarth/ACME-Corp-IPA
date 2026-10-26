# web-app Specification

## Purpose
ACME Corp IPA is the browser application where people upload invoices, follow them through the agent pipeline, decide held invoices, release approved payments, and audit every outcome and its reasoning.

## Requirements

### Requirement: App shell and sidebar navigation (F21)
The app SHALL be titled "ACME Corp IPA" and show a persistent left sidebar with the name, the tagline "Invoice Processing Automation", and menu items in this order: Home, Invoice Queue, Payment Queue, Invoice Elevated Review, Invoice Resolution Audit, Payments. An Admin item with its own icon and no badge SHALL be pinned toward the bottom of the sidebar, visually separated from the main menu and above the provider footer. The active page SHALL be highlighted.

#### Scenario: Menu order and active page
- **WHEN** a user opens the Payment Queue page
- **THEN** the sidebar lists the six items in the order Home, Invoice Queue, Payment Queue, Invoice Elevated Review, Invoice Resolution Audit, Payments, and highlights Payment Queue
- **AND** Admin appears separately near the bottom of the sidebar, above the provider footer

#### Scenario: Admin is active
- **WHEN** a user clicks Admin
- **THEN** the Admin page opens and Admin is highlighted

#### Scenario: Direct navigation by URL
- **WHEN** a user loads the Invoice Elevated Review page's URL directly
- **THEN** the shell renders with that page active and no other page content shown

#### Scenario: Collapsed sidebar keeps the order
- **WHEN** the window is narrower than 960 px and the sidebar shows icons only
- **THEN** the icons appear in the same order as the full menu, with the Admin icon still at the bottom

### Requirement: Sidebar count badges (F21)
Invoice Queue, Invoice Elevated Review, and Payment Queue SHALL each show a count badge of their waiting items, visible from every page and refreshed with live data. A badge with a count of zero SHALL be hidden.

#### Scenario: Badge reflects waiting work
- **WHEN** two invoices are Awaiting review and the user is on the Home page
- **THEN** the Invoice Elevated Review badge shows 2

#### Scenario: Badge drops after a decision
- **WHEN** a reviewer confirms a decision on one of two held invoices
- **THEN** the Invoice Elevated Review badge shows 1 without a page reload

### Requirement: Responsive sidebar (F21)
Below 960 px viewport width the sidebar SHALL collapse to icons only and open as an overlay when toggled; at 960 px and wider it SHALL be fully expanded and persistent.

#### Scenario: Narrow viewport
- **WHEN** the viewport is 800 px wide
- **THEN** the sidebar shows icons only, and activating the menu toggle opens it as an overlay over the page

#### Scenario: Overlay closes after navigation
- **WHEN** the overlay sidebar is open and the user selects a menu item
- **THEN** the app navigates to that page and the overlay closes

### Requirement: Active LLM provider in footer (F21)
The sidebar footer SHALL show the active LLM provider (Grok or Claude) and model name from the `llm` field of `/api/stats`.

#### Scenario: Provider shown
- **WHEN** the backend runs with `LLM_PROVIDER=claude` and `CLAUDE_MODEL=claude-sonnet-5-5`
- **THEN** the sidebar footer reads Claude and claude-sonnet-5-5

### Requirement: Home page upload (F22)
The Home page SHALL show the header "Welcome to ACME Corp IPA" with one line describing the system, a drop zone that accepts one or many files and highlights while files hover over it, and a Browse button that opens a multi-select picker limited to .pdf, .txt, .csv, .json, .xml, and .eml.

#### Scenario: Multi-file drop
- **WHEN** a user drops three supported files on the drop zone
- **THEN** all three are uploaded and each appears as a row in the upload list

#### Scenario: Hover highlight
- **WHEN** files are dragged over the drop zone
- **THEN** the drop zone is visually highlighted until the files leave or are dropped

### Requirement: Client-side upload validation (F22)
The app SHALL refuse, before uploading, any file with an unsupported extension, a size over 10 MB, or a size of zero, showing an inline error on that file's row while still uploading the valid files.

#### Scenario: Mixed valid and invalid files
- **WHEN** a user drops invoice.pdf (200 KB), photo.png, and big.pdf (12 MB)
- **THEN** only invoice.pdf is uploaded, photo.png shows a wrong-type error, and big.pdf shows an over-10 MB error

#### Scenario: Empty file
- **WHEN** a user selects a 0-byte invoice.txt
- **THEN** it is not uploaded and its row shows an empty-file error

### Requirement: Upload progress and confirmation (F22)
Each uploaded file's row SHALL show name, size, and upload progress, then "Queued" once the backend accepts it, or the backend's error. After uploads finish the page SHALL show a toast with the number of files accepted and a "View in Invoice Queue" link.

#### Scenario: Accepted uploads
- **WHEN** two files upload and the backend returns 202 for both
- **THEN** both rows show Queued, a toast says 2 files were accepted, and a "View in Invoice Queue" link is shown

#### Scenario: Server rejects a file
- **WHEN** the backend refuses one file of two
- **THEN** that row shows the backend's error and the toast says 1 file was accepted

### Requirement: Shared invoice table behavior
Every table in the app SHALL support column sorting, a search box, pagination, a status chip whose color is consistent for the same status across all pages, and a row click that opens the invoice detail drawer once F30 is delivered.

#### Scenario: Consistent status chip
- **WHEN** an invoice with status Awaiting review appears in both the Invoice Queue and Invoice Elevated Review
- **THEN** its status chip has the same label and color on both pages

#### Scenario: Search filters rows
- **WHEN** a user types "Widgets Inc" in a table's search box
- **THEN** only rows whose text matches remain and pagination recounts

### Requirement: Invoice Queue page (F23)
The Invoice Queue SHALL list every invoice that is not yet resolved, with columns File (name and format icon), Invoice # / Vendor ("Extracting..." until known), Amount (USD), Stage (a 5-step strip: Uploaded, Extracting, Validating, Deciding, Awaiting review), Status (Processing, Retrying extraction, or Awaiting review), and Uploaded / Time in stage.

#### Scenario: Before extraction
- **WHEN** an invoice has just been uploaded
- **THEN** its row shows "Extracting..." in Invoice # / Vendor and the stage strip marks Uploaded

#### Scenario: Stage advances without reload
- **WHEN** the backend moves an invoice from Validating to Deciding
- **THEN** the row's stage strip shows Deciding without a page reload

#### Scenario: Resolved invoice leaves the queue
- **WHEN** an invoice is approved or rejected
- **THEN** it leaves the Invoice Queue; a rejected one appears in the Invoice Resolution Audit, and an approved one appears in the Payment Queue when payment delay is on, or as Paid in the Invoice Resolution Audit and in Payments when delay is off

### Requirement: Invoice Resolution Audit page (F24)
The Audit SHALL list every resolved invoice with Invoice # / Vendor / Amount (USD), Final status (Paid, Revised, Rejected, Duplicate, Superseded, or Credit confirmed), Decided by (Auto (rules), AI VP with provider and model, or the reviewer's name), Key findings (up to 3 chips), and Completed (timestamp and total processing time). It SHALL filter by status and date.

#### Scenario: Superseded original
- **WHEN** INV-1004 has been replaced by its revision
- **THEN** INV-1004 appears with Final status Superseded and a Superseded by revision finding chip

#### Scenario: Revised paid invoice
- **WHEN** a revision of an already-paid invoice is approved and its delta is paid, or it has the same total and nothing is due
- **THEN** the revision appears with Final status Revised, styled with its own status chip, and the status filter offers Revised

#### Scenario: More than three findings
- **WHEN** INV-1009 has four findings
- **THEN** its row shows three finding chips and indicates there are more

#### Scenario: Filter by status
- **WHEN** a user filters to Rejected
- **THEN** only invoices with Final status Rejected are listed

### Requirement: Audit rationale timeline (F24)
Expanding an Audit row SHALL show a timeline with one entry per stage: extraction notes and retries, validation findings with evidence, the rules that fired, each AI VP draft with the Critic's response and the provider and model behind each, the reviewer's rationale when present, and the payment or rejection record.

#### Scenario: VP and Critic rounds shown
- **WHEN** a user expands an invoice whose AI VP draft was revised once after a Critic critique
- **THEN** the timeline shows both drafts, the Critic response to each, and the provider and model for every entry

### Requirement: Invoice Elevated Review page (F25)
The Elevated Review page SHALL list invoices awaiting a person with Invoice # / Vendor / Amount (USD), Why it's held (the warning findings or a revision lowering a paid total), AI recommendation (outcome and one-line rationale), Waiting since, and Actions (Approve, Reject, View details).

#### Scenario: Price variance hold
- **WHEN** INV-1010 is held
- **THEN** its row shows a Price variance finding under Why it's held and the AI VP's recommended outcome and rationale

#### Scenario: Payment failure hold
- **WHEN** an invoice's payment failed 3 times
- **THEN** its row shows "Payment failed" with the last error under Why it's held; Approve requeues it to the Payment Queue and Reject sends it to the Audit as Rejected

### Requirement: Review decision dialog (F25)
Clicking Approve or Reject SHALL open a dialog showing the invoice summary, findings, and AI recommendation, with a required reviewer name field and a required rationale field. Confirming SHALL send the decision to the backend; on success the row leaves the table, the badge drops, and a toast confirms the result.

#### Scenario: Approve
- **WHEN** a reviewer approves INV-1010 with a valid name and rationale
- **THEN** the decision is sent, INV-1010 leaves Elevated Review and appears in the Payment Queue, and a toast confirms the approval

#### Scenario: Reject
- **WHEN** a reviewer rejects a held invoice with a valid name and rationale
- **THEN** the invoice leaves Elevated Review and appears in the Audit as Rejected with the reviewer's name in Decided by

### Requirement: Reviewer and releaser name field
Every name field (review, pay, and admin save dialogs) SHALL be required, accept 1 to 50 characters after trimming leading and trailing spaces, show a counter of characters left, and be prefilled with the last name used in this browser.

#### Scenario: Blank name
- **WHEN** the name field contains only spaces
- **THEN** the confirm button is disabled and the field shows a required error

#### Scenario: Too long
- **WHEN** a user types 51 non-space characters
- **THEN** the field shows an over-limit error and the confirm button is disabled

#### Scenario: Remembered name
- **WHEN** a reviewer confirmed a decision as "Dana Reyes" and later opens any review, pay, or admin save dialog in the same browser
- **THEN** the name field is prefilled with "Dana Reyes"

### Requirement: Review rationale field
The review dialog's rationale SHALL be required and at least 15 characters after trimming; the confirm button SHALL stay disabled until it is.

#### Scenario: Short rationale
- **WHEN** the rationale is "looks fine"
- **THEN** the confirm button is disabled and the field explains the 15-character minimum

### Requirement: Stale review decision (F25)
If the backend reports the invoice is no longer awaiting review (HTTP 409), the dialog SHALL tell the user someone else already decided it and refresh the Elevated Review list.

#### Scenario: Concurrent reviewers
- **WHEN** two reviewers open the same invoice and the second confirms after the first
- **THEN** the second sees a message that the invoice was already decided, and the row is gone after the refresh

### Requirement: Credit or refund holds (F25)
When the held invoice is a revision lowering a paid total, the row SHALL show the amount overpaid, and the actions SHALL read Credit confirmed and Reject revision. The rationale SHALL be required to record the credit note or refund and its amount, and neither action pays anything.

#### Scenario: Credit confirmed
- **WHEN** a reviewer clicks Credit confirmed on a revision lowering a paid $5,940 invoice to $5,000 and records "Credit note CN-88 for $940 agreed with vendor"
- **THEN** the row leaves Elevated Review, the invoice appears in the Audit as Credit confirmed, and no row is added to the Payment Queue

#### Scenario: Overpaid amount shown
- **WHEN** a credit hold row is displayed for that revision
- **THEN** it shows $940.00 overpaid

### Requirement: Payment Queue page (F40)
The Payment Queue SHALL show a header with queued count and total, the payment mode with a link to Admin, and a table with Select, Invoice # / Vendor, Amount (USD), Type (Full invoice, Revision replacing original, or Revision delta), Approved by, Queued at, Status (Queued, Paying, or Failed with the error), and a Pay now action. The mode SHALL read as in the Delayed and Immediate mode header scenarios; Pay all, Pay selected, and Pay now SHALL be available in both modes.

#### Scenario: Header totals
- **WHEN** three payments totalling $14,690.00 are queued
- **THEN** the header shows 3 queued and $14,690.00

#### Scenario: Delayed mode header
- **WHEN** payment delay is on and end of day is turned on with the default time and timezone
- **THEN** the header shows the next batch as "Today 5:00 PM CT" (or tomorrow's) and pay when queue empty as on, with a link to Admin

#### Scenario: Immediate mode header
- **WHEN** payment delay is off
- **THEN** the header says approved invoices are paid at approval, shows no next batch time, and links to Admin

#### Scenario: Failed row
- **WHEN** a payment failed in the last batch
- **THEN** its row shows Failed with the error text and stays in the queue until it is retried

### Requirement: Pay actions and confirm dialog (F40)
Pay all, Pay selected (enabled only when rows are checked), and each row's Pay now SHALL open a confirm dialog showing row count, total, and the name field. Confirming SHALL start a batch for all rows, the checked rows, or that row; a 409 because a batch is already running SHALL be shown as a message, not an error page.

#### Scenario: Pay selected
- **WHEN** a user checks two rows totalling $8,690.00 and clicks Pay selected
- **THEN** the dialog shows 2 rows and $8,690.00, and confirming as "Sam Ortiz" starts a batch for those two rows only

#### Scenario: Batch already running
- **WHEN** a user confirms Pay all while another batch is running
- **THEN** the dialog shows that a batch is already in progress and no second batch starts

### Requirement: Batch progress and summary (F40)
While a batch runs, its rows SHALL show Paying and their pay controls SHALL be disabled. When it ends, paid rows SHALL leave the Payment Queue for Payments and a toast SHALL summarize the batch, for example "Batch B-0142: 7 paid, $37,620, 0 failed".

#### Scenario: Batch completes
- **WHEN** a batch pays 7 rows totalling $37,620 with no failures
- **THEN** those rows leave the Payment Queue, appear in Payments, and the toast reads "Batch B-0142: 7 paid, $37,620, 0 failed" with the real batch ID

### Requirement: Revision swap in Payment Queue (F40)
When a revision replaces a queued invoice, the original's row SHALL disappear from the Payment Queue, the revision's row SHALL appear with its full total and Type Revision replacing original, and a toast SHALL explain the swap.

#### Scenario: INV-1004 replaced
- **WHEN** INV-1004 ($1,890.00) is queued and its revision is approved for $5,940.00
- **THEN** the INV-1004 row disappears, an INV-1004 R1 row appears for $5,940.00, and a toast explains that the revision replaced the original

### Requirement: Payments page (F26)
The Payments page SHALL list every paid invoice with Payment ID, Invoice # / Vendor (linked to its audit entry), Amount paid (USD) plus original amount and currency when not USD, Approved by, Paid at, Idempotency key, Batch (ID and trigger), and Released by. A footer SHALL show the total paid for the current filter, and it SHALL filter by date and vendor.

#### Scenario: Foreign currency payment
- **WHEN** INV-1014 was paid from a EUR 4,125.00 invoice
- **THEN** its row shows the USD amount paid and EUR 4,125.00 as the original amount

#### Scenario: Delta payment
- **WHEN** a revision of a paid invoice was paid only its delta
- **THEN** the amount cell shows "Delta for R1" and the revised total

#### Scenario: Released by
- **WHEN** a payment came from the idle batch trigger
- **THEN** Batch shows Invoice Queue idle and Released by shows System

#### Scenario: Filtered total
- **WHEN** a user filters Payments to one vendor
- **THEN** the footer shows the sum of Amount paid for only that vendor's rows

### Requirement: Live data refresh
All pages and sidebar badges SHALL reflect backend changes without a manual reload, by polling every 3 seconds; once F29 is delivered they SHALL update from the server event stream and fall back to 3-second polling while the stream is disconnected.

#### Scenario: Polling
- **WHEN** the event stream is unavailable and an invoice changes stage
- **THEN** the Invoice Queue shows the new stage within 3 seconds plus request time

#### Scenario: Event stream (P1, F29)
- **WHEN** the event stream is connected and the backend emits `invoice.stage_changed`
- **THEN** the affected row updates without waiting for a poll

#### Scenario: Stream drops (P1, F29)
- **WHEN** the event stream disconnects
- **THEN** the app resumes polling every 3 seconds and switches back when the stream reconnects

### Requirement: Invoice detail drawer (P1, F30)
Clicking a row in any table SHALL open a drawer with a preview of the original file beside the extracted fields, the findings, and the full stage timeline from the audit ledger.

#### Scenario: Open from Payments
- **WHEN** a user clicks the INV-1001 row on the Payments page
- **THEN** the drawer shows the original text file, the extracted vendor, line items, and totals, no findings, and the stage timeline through payment

#### Scenario: Unpreviewable file
- **WHEN** the original file cannot be rendered inline
- **THEN** the drawer offers a download of the original file instead of the preview

### Requirement: Home summary tiles (P1, F31)
The Home page SHALL show tiles for In queue, Awaiting review, Paid today, and Rejected today, kept current with live data.

#### Scenario: Tiles reflect counts
- **WHEN** 3 invoices were rejected today
- **THEN** the Rejected today tile shows 3

### Requirement: CSV export (P2, F35)
The Invoice Resolution Audit and Payments pages SHALL offer an export of the rows matching the current filter as a CSV file.

#### Scenario: Export filtered audit
- **WHEN** the Audit is filtered to Rejected and the user clicks Export CSV
- **THEN** the downloaded CSV contains only the Rejected invoices

### Requirement: One-command local setup (P1, F33)
From a fresh clone, `make setup` SHALL install backend and frontend dependencies and seed `acme.db`, and `make dev` SHALL start the FastAPI backend and the Angular dev server together so the app is usable in a browser. Without an LLM key both servers SHALL still start, and the startup output SHALL warn that invoices cannot be processed until a key is set.

#### Scenario: Fresh clone
- **WHEN** a developer with Python and Node installed and an LLM key in `.env` runs `make setup && make dev`
- **THEN** both servers start, and opening the Angular dev server URL shows the Home page with the sidebar footer showing the active provider

#### Scenario: Fresh clone without a key
- **WHEN** a developer runs `make dev` (or `run.sh`) with no LLM key set
- **THEN** both servers start, the terminal prints a warning naming the variable to set, and the Home page shows the missing-key banner

#### Scenario: Stopping dev
- **WHEN** the developer stops `make dev` with Ctrl+C
- **THEN** both the backend and the frontend dev servers stop

### Requirement: Frontend tests (P1, F32)
The frontend SHALL have:
- component tests for the drop zone, the review dialog, the pay dialog, and the missing-key banner
- one end-to-end run that uploads 3 files, reviews one held invoice, clicks Pay all, and finds the paid invoices in Payments

#### Scenario: End-to-end happy path
- **WHEN** the end-to-end test runs against a backend started by the test harness with the test-only fake model
- **THEN** it uploads 3 files including invoice_1010.txt, approves INV-1010 in Elevated Review, pays all from the Payment Queue, and sees them in Payments

### Requirement: Missing LLM key banner
While `/api/stats` reports `llm.configured` false, every page SHALL show a persistent, prominent error banner reading "No LLM token provided — the app cannot process invoices without it". The banner names the variable from `llm.missing_key` and says to set it in `.env` and restart the backend. The Home drop zone and Browse button SHALL be disabled with the same explanation. Pages that need no LLM (the lists, review decisions, payment actions) SHALL stay usable.

#### Scenario: App loads without a key
- **WHEN** the backend runs with no `XAI_API_KEY` and `LLM_PROVIDER=grok`
- **THEN** the app loads, the banner reads "No LLM token provided — the app cannot process invoices without it" and names `XAI_API_KEY`
- **AND** the drop zone and Browse button are disabled

#### Scenario: Refused upload explained
- **WHEN** an upload reaches the API while no key is configured and the API answers 503
- **THEN** the upload row shows the API's message naming the missing variable

#### Scenario: Other pages stay usable
- **WHEN** no key is configured and a reviewer approves a held invoice, then clicks Pay all
- **THEN** both actions succeed while the banner stays visible

#### Scenario: Key added
- **WHEN** the backend restarts with a key and the next stats poll reports `llm.configured` true
- **THEN** the banner disappears and the drop zone is enabled without a page reload

### Requirement: Admin page (F41)
The Admin page SHALL show a payment timing form loaded from the backend: a Delay payments toggle; a Pay at end of day toggle with a time picker and an IANA timezone picker; and a Pay when the Invoice Queue is empty toggle. It SHALL show who last saved the settings and when, and say what the current mode does in one sentence.

#### Scenario: Defaults shown
- **WHEN** a user opens Admin on a new database
- **THEN** Delay payments is on, Pay at end of day is off, Pay when the Invoice Queue is empty is on, and the page explains that approved invoices wait in the Payment Queue and are paid when the Invoice Queue is empty

#### Scenario: Last saved by
- **WHEN** "Dana" saved the settings earlier
- **THEN** the page shows they were last saved by Dana with the time

### Requirement: Delay toggle reveals batch options
The end-of-day and queue-empty options SHALL be shown and editable only while Delay payments is on. The defaults SHALL be Delay payments on, Pay at end of day off, and Pay when the Invoice Queue is empty on. The time and timezone fields SHALL default to 5:00 PM Central Time (America/Chicago) and SHALL be enabled only while Pay at end of day is on.

#### Scenario: Turning end of day on
- **WHEN** a user turns Pay at end of day on from the defaults
- **THEN** the time and timezone fields become editable showing 5:00 PM and Central Time (America/Chicago)

#### Scenario: End of day off
- **WHEN** Pay at end of day is turned off
- **THEN** the time and timezone fields are disabled but keep their values

#### Scenario: Turning delay off
- **WHEN** Delay payments is turned off
- **THEN** the batch options are hidden and the page warns that saving will pay everything currently queued

### Requirement: Saving admin settings
Save SHALL be enabled only when the form has changes and is valid, and SHALL open a confirm dialog summarizing the changes with the shared name field. Confirming SHALL save through the backend; on success a toast SHALL confirm and the form SHALL show the saved values. A 422 SHALL be shown on the offending field. A `settings.updated` event from another browser SHALL refresh an unchanged form, or warn that the settings changed when the form has unsaved edits.

#### Scenario: Save with a name
- **WHEN** a user changes the end-of-day time to 3:00 PM and confirms as "Sam Ortiz"
- **THEN** the backend receives the new time with `updated_by` "Sam Ortiz", a toast confirms the save, and the page shows last saved by Sam Ortiz

#### Scenario: Invalid timezone from the backend
- **WHEN** the backend answers 422 for the timezone
- **THEN** the timezone field shows the error and nothing else changes

#### Scenario: Changed elsewhere
- **WHEN** the user has unsaved edits and another browser saves new settings
- **THEN** the page warns that the settings changed and offers to reload them

### Requirement: Payee threshold holds in Elevated Review
A row held for `PAYEE_CUMULATIVE_THRESHOLD` SHALL show, under Why it's held, "Payee total" with the amount and window, and the contributing invoice numbers. A pulled invoice that had been approved SHALL be marked "Pulled from Payment Queue". Approve SHALL return it to the Payment Queue and Reject SHALL send it to the Audit as Rejected.

#### Scenario: Split set held
- **WHEN** INV-1018, INV-1019, and INV-1020 are held for the payee threshold
- **THEN** each row shows "Payee total $29,000.00 in 30 days" and lists INV-1018, INV-1019, and INV-1020, and INV-1018 is marked "Pulled from Payment Queue"

#### Scenario: Approve returns to the Payment Queue
- **WHEN** a reviewer approves INV-1018 with a valid name and rationale
- **THEN** INV-1018 leaves Elevated Review and appears in the Payment Queue

### Requirement: Retroactive flags in the Audit timeline
The Audit rationale timeline SHALL show retroactive `PAYEE_CUMULATIVE_THRESHOLD` flags as entries labelled "Flagged after resolution", with the triggering invoice, the payee total, and the time. The row's Final status SHALL stay unchanged and the key findings SHALL include the flag.

#### Scenario: Paid invoice flagged later
- **WHEN** a user expands INV-1018 in the Audit after it was paid at approval and INV-1019 later raised the finding
- **THEN** the timeline shows "Flagged after resolution" naming INV-1019 and the payee total, and the Final status is still Paid
