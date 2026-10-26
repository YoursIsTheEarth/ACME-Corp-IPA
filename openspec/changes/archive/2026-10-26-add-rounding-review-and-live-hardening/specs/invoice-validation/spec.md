## MODIFIED Requirements

### Requirement: Arithmetic reconciliation (F9)
The system SHALL check that each line's `quantity × unit_price` equals its `amount`, that the line amounts sum to `subtotal`, and that `subtotal + tax + shipping` equals `total`. When `subtotal` is absent, the line sum SHALL stand in for it, and absent `tax` or `shipping` count as zero. Each check SHALL compare the absolute difference between the expected and stated values:
- Under $0.01 SHALL raise nothing.
- From $0.01 up to and including `MATH_ROUNDING_TOLERANCE_USD` (default 1.00) SHALL yield WARNING `MATH_ROUNDING`, whose evidence holds the check, the expected and actual values, the difference, and the tolerance.
- Over the tolerance SHALL yield CRITICAL `MATH_MISMATCH`, with the expected and actual values as evidence.

A line with neither an amount nor a unit price SHALL yield CRITICAL `MATH_MISMATCH`. A tolerance of 0 SHALL make every difference of $0.01 or more a `MATH_MISMATCH`.

#### Scenario: Line sum disagrees with subtotal
- **WHEN** INV-1009 states a subtotal of $1,000.00 but its lines sum to -$250.00
- **THEN** a CRITICAL `MATH_MISMATCH` finding cites expected -250.00 and actual 1000.00

#### Scenario: Shipping included in the total
- **WHEN** INV-1010 has subtotal $6,700, tax $335, and shipping $150, against a total of $7,185
- **THEN** neither `MATH_MISMATCH` nor `MATH_ROUNDING` is raised

#### Scenario: No subtotal printed
- **WHEN** INV-1002 states only a total of $15,000.00 and its one line is 20 × $750.00
- **THEN** neither `MATH_MISMATCH` nor `MATH_ROUNDING` is raised

#### Scenario: One-cent discrepancy
- **WHEN** an invoice's stated total is $0.02 above `subtotal + tax + shipping` with the default tolerance
- **THEN** a WARNING `MATH_ROUNDING` finding cites the 0.02 difference and no `MATH_MISMATCH` is raised

#### Scenario: Difference at the tolerance
- **WHEN** an invoice's stated total is exactly $1.00 above `subtotal + tax + shipping` with the default tolerance
- **THEN** a WARNING `MATH_ROUNDING` finding is raised

#### Scenario: Difference over the tolerance
- **WHEN** INV-1007's total of $15,525.00 is $110.00 below its subtotal plus tax of $15,635.00
- **THEN** a CRITICAL `MATH_MISMATCH` finding is raised

#### Scenario: Tolerance disabled
- **WHEN** `MATH_ROUNDING_TOLERANCE_USD=0` and an invoice's total is $0.02 off
- **THEN** a CRITICAL `MATH_MISMATCH` finding is raised

### Requirement: Fraud signal scoring (F11, P1)
A weighted fraud score SHALL sum the signals present: urgency language, a wire-transfer request, "Immediate" payment terms, a relative or pre-invoice due date, `UNKNOWN_VENDOR`, `SUSPICIOUS_ADDRESS` (exactly when the address assessment finds it implausible), `NEAR_THRESHOLD`, `PAYEE_CUMULATIVE_THRESHOLD` (default weight 0.25), and `PROMPT_INJECTION_SUSPECTED` (default weight 0.60, the default threshold). A score reaching the threshold SHALL yield CRITICAL `FRAUD_SUSPECTED` naming its signals. A `FRAUD_SIGNAL_WEIGHTS` setting SHALL be merged over the default weights: a signal it omits keeps its default weight, and a signal it sets to 0 is turned off.

#### Scenario: Fraudulent invoice
- **WHEN** INV-1003 is validated (urgent wording, wire transfer, Immediate terms, due "yesterday", unknown vendor)
- **THEN** its score meets the threshold and a CRITICAL `FRAUD_SUSPECTED` finding lists those signals

#### Scenario: Clean invoices stay under the threshold
- **WHEN** INV-1001, 1004, 1006, 1011, 1012, 1014, and 1015 are validated
- **THEN** none raises `FRAUD_SUSPECTED`

#### Scenario: A single signal does not trip fraud
- **WHEN** INV-1005's only fraud signal is `SUSPICIOUS_ADDRESS`
- **THEN** no `FRAUD_SUSPECTED` finding is raised

#### Scenario: Prompt injection trips fraud
- **WHEN** INV-1017 is validated with `PROMPT_INJECTION_SUSPECTED` and `UNKNOWN_VENDOR`
- **THEN** its score meets the threshold and `FRAUD_SUSPECTED` lists `prompt_injection` and `unknown_vendor`

#### Scenario: Split invoicing alone does not trip fraud
- **WHEN** INV-1019 is validated with `PAYEE_CUMULATIVE_THRESHOLD` and `NEAR_THRESHOLD` as its only signals
- **THEN** its score (0.35) is below the threshold and no `FRAUD_SUSPECTED` finding is raised

#### Scenario: Partial weights setting keeps the other defaults
- **WHEN** `FRAUD_SIGNAL_WEIGHTS` sets only the seven original signals and INV-1017 is validated
- **THEN** `prompt_injection` keeps its default weight of 0.60 and `FRAUD_SUSPECTED` is raised
