## ADDED Requirements

### Requirement: Payee threshold hold decision
For a run held with a `payee_threshold` hold, the review view SHALL show the reason "Payee cumulative threshold" with the payee total, the window, and the contributing invoices (number, date, amount, status). `approve` SHALL requeue the payment and `reject` SHALL resolve the run as Rejected, per `payment-processing`. The review input rules and 409 stale-decision handling SHALL be the same as for other holds.

#### Scenario: Review view shows contributing invoices
- **WHEN** INV-1018 is held after INV-1019 raised `PAYEE_CUMULATIVE_THRESHOLD`
- **THEN** its `view=review` entry has reason "Payee cumulative threshold", total $19,250.00, and contributing invoices INV-1018 and INV-1019

#### Scenario: Approve requeues
- **WHEN** a reviewer approves INV-1018's `payee_threshold` hold
- **THEN** the response is 200 and INV-1018 appears in `/api/payment-queue` as `queued` when payment delay is on

#### Scenario: Pull is announced
- **WHEN** INV-1018's queued payment is pulled into review
- **THEN** `/api/events` emits `payment.cancelled` for its row and `invoice.stage_changed` with status Awaiting review

### Requirement: Retroactive flags in invoice detail
The invoice detail SHALL include retroactive `PAYEE_CUMULATIVE_THRESHOLD` flags recorded after the invoice resolved, as timeline entries with the triggering invoice, the payee total, and when the flag was recorded.

#### Scenario: Paid invoice detail
- **WHEN** a client requests `GET /api/invoices/{id}` for INV-1018 after it was paid at approval and INV-1019 later raised the finding
- **THEN** the timeline contains a retroactive flag entry naming INV-1019 and the payee total
