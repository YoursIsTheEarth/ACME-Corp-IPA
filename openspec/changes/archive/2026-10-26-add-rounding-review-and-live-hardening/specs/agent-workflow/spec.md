## MODIFIED Requirements

### Requirement: Adversarial inputs fail closed
The workflow SHALL never pay an invoice it cannot extract or verify.

#### Scenario: Total off by one cent
- **WHEN** an invoice's stated total differs from line items plus tax and shipping by $0.01
- **THEN** a `MATH_ROUNDING` WARNING finding is raised and the outcome is NEEDS_REVIEW, so the invoice is not paid without a person's decision

#### Scenario: Total off by more than the rounding tolerance
- **WHEN** an invoice's stated total differs from line items plus tax and shipping by $1.01 with the default tolerance
- **THEN** a `MATH_MISMATCH` CRITICAL finding is raised and the outcome is REJECT

#### Scenario: Lookalike vendor name
- **WHEN** an invoice vendor name uses a lookalike character (for example Cyrillic "а" in a known vendor name)
- **THEN** the vendor is not matched as approved and the invoice is not auto-approved

#### Scenario: Empty file
- **WHEN** a zero-byte invoice file is processed
- **THEN** the outcome is REJECT with `EXTRACTION_FAILED`
