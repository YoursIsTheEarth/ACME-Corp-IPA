## ADDED Requirements

### Requirement: Payee threshold pulls queued payments into review
When an invoice's disposition carries `PAYEE_CUMULATIVE_THRESHOLD`, every other contributing invoice whose payment row is `queued` or `failed` SHALL have that row cancelled and SHALL be held in Elevated Review. The hold kind SHALL be `payee_threshold`, it SHALL carry the same finding, and a `payment.cancelled` event SHALL be emitted. This SHALL happen under the batch lock, so a row cannot be both pulled and paid.

#### Scenario: Earlier split invoice pulled
- **WHEN** INV-1018 is queued for $9,750.00 and INV-1019 then raises `PAYEE_CUMULATIVE_THRESHOLD`
- **THEN** INV-1018's queue row is cancelled, INV-1018 is Awaiting review with a `payee_threshold` hold, and no batch pays it

#### Scenario: Pulled during a running batch
- **WHEN** a contributing invoice's row is `paying` in a running batch when the finding fires
- **THEN** the pull waits for the batch lock and, once the row is paid, treats the invoice as paid

### Requirement: Payee threshold flags on resolved and held invoices
For contributing invoices that are already paid, rejected, superseded, or otherwise resolved, the system SHALL record the finding in their audit trail as a retroactive flag. Their final status SHALL NOT change and paid money SHALL NOT be recalled or reversed. For contributing invoices already Awaiting review, the finding SHALL be added to their hold reasons, with the latest payee total.

#### Scenario: Paid invoice flagged after the fact
- **WHEN** payment delay is off, INV-1018 was paid at approval, and INV-1019 then raises `PAYEE_CUMULATIVE_THRESHOLD`
- **THEN** INV-1018 stays Paid and its audit trail gains a retroactive `PAYEE_CUMULATIVE_THRESHOLD` entry naming INV-1019

#### Scenario: Held invoice gains the reason
- **WHEN** INV-1018 and INV-1019 are Awaiting review and INV-1020 raises `PAYEE_CUMULATIVE_THRESHOLD`
- **THEN** both holds list the finding with the payee total of $29,000.00

### Requirement: Payee threshold hold decisions
A `payee_threshold` hold on an invoice that had been approved SHALL be decidable like any other hold. Approve SHALL requeue the invoice as a new `queued` row with the same kind, amount, and idempotency key, which is paid by the next batch, or at once when payment delay is off. Reject SHALL resolve the run as Rejected with the reviewer's rationale and SHALL queue nothing.

#### Scenario: Approve requeues
- **WHEN** a reviewer approves INV-1018's `payee_threshold` hold with payment delay on
- **THEN** a fresh `queued` row for $9,750.00 exists and the next batch pays it once

#### Scenario: Reject closes it
- **WHEN** a reviewer rejects INV-1018's `payee_threshold` hold
- **THEN** the run is Rejected, no queue row is payable, and the payee ledger records outcome Rejected
