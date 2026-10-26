## MODIFIED Requirements

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

### Requirement: Payment Queue page (F40)
The Payment Queue SHALL show a header with queued count and total, the payment mode with a link to Admin, and a table with Select, Invoice # / Vendor, Amount (USD), Type (Full invoice, Revision replacing original, or Revision delta), Approved by, Queued at, Status (Queued, Paying, or Failed with the error), and a Pay now action. With delay on, the header SHALL show the next end-of-day batch (for example "Today 5:00 PM CT") when it is scheduled and whether paying when the queue is empty is on. With delay off, it SHALL say payments are made at approval. Pay all, Pay selected, and Pay now SHALL be available in both modes.

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

## ADDED Requirements

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
