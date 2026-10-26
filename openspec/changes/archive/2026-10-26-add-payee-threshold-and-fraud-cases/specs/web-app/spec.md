## ADDED Requirements

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
