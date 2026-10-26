## MODIFIED Requirements

### Requirement: Warning and info finding codes
The catalog's WARNING codes SHALL be `UNKNOWN_VENDOR`, `MISSING_DUE_DATE`, `INVALID_DUE_DATE`, `DUE_BEFORE_INVOICE_DATE`, `PRICE_VARIANCE`, `SUSPICIOUS_ADDRESS`, `REVISION_CREDIT_DUE`, `INVOICE_NUMBER_REUSED`, `CURRENCY_UNSUPPORTED`, `PAYEE_CUMULATIVE_THRESHOLD`, and `MATH_ROUNDING`. Its INFO codes SHALL be `REVISION`, `SUPERSEDED_BY_REVISION`, `NEAR_THRESHOLD`, and `CURRENCY_CONVERTED`.

#### Scenario: Info code
- **WHEN** the catalog is asked for the severity of `NEAR_THRESHOLD`
- **THEN** it returns INFO

#### Scenario: Canonical severity
- **WHEN** the catalog is asked for the severity of `CURRENCY_UNSUPPORTED`
- **THEN** it returns WARNING

#### Scenario: Payee threshold is a warning
- **WHEN** the catalog is asked for the severity of `PAYEE_CUMULATIVE_THRESHOLD`
- **THEN** it returns WARNING

#### Scenario: Rounding difference is a warning
- **WHEN** the catalog is asked for the severity of `MATH_ROUNDING`
- **THEN** it returns WARNING

#### Scenario: Codes serialize verbatim
- **WHEN** a finding with code `STOCK_EXCEEDED` is serialized to JSON
- **THEN** the JSON value is exactly "STOCK_EXCEEDED"
