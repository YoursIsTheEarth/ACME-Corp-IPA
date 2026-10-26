## MODIFIED Requirements

### Requirement: Fraud signal scoring (F11, P1)
The system SHALL compute a weighted fraud score from these signals: urgency language, a wire-transfer request, "Immediate" payment terms, a relative or pre-invoice due date, `UNKNOWN_VENDOR`, `SUSPICIOUS_ADDRESS`, and `NEAR_THRESHOLD`. The `SUSPICIOUS_ADDRESS` signal SHALL be present exactly when the address plausibility assessment judged the vendor address implausible. A score at or above the configured threshold SHALL yield CRITICAL `FRAUD_SUSPECTED`, which lists the contributing signals.

#### Scenario: Fraudulent invoice
- **WHEN** INV-1003 is validated (urgent wording, wire transfer, Immediate terms, due "yesterday", unknown vendor)
- **THEN** its score meets the threshold and a CRITICAL `FRAUD_SUSPECTED` finding lists those signals

#### Scenario: Clean invoices stay under the threshold
- **WHEN** INV-1001, 1004, 1006, 1011, 1012, 1014, and 1015 are validated
- **THEN** none raises `FRAUD_SUSPECTED`

#### Scenario: A single signal does not trip fraud
- **WHEN** INV-1005's only fraud signal is `SUSPICIOUS_ADDRESS`
- **THEN** no `FRAUD_SUSPECTED` finding is raised

### Requirement: Suspicious address signal (F11, P1)
For every invoice with a vendor address, the Validation stage SHALL ask the configured LLM whether the address is plausible for a business supplier. The answer SHALL be structured: a plausible yes/no, a short reason, and a confidence. Implausible examples include government buildings, landmarks, residential-only or PO-box-only addresses, and incomplete or nonsensical addresses. An implausible verdict SHALL yield WARNING `SUSPICIOUS_ADDRESS` with `source` = `llm`, the address and the model's reason as evidence. The assessment SHALL run whether or not the LLM requested it during the tool loop. The address SHALL be passed as untrusted data. No configured list of addresses SHALL be consulted. The finding is subject to the cap on LLM-sourced findings, so it can only tighten an outcome.

#### Scenario: Government landmark address
- **WHEN** INV-1005 lists "1600 Pennsylvania Ave, Washington, DC 20500"
- **THEN** the LLM judges it implausible for a supplier
- **AND** a WARNING `SUSPICIOUS_ADDRESS` finding is raised with `source` = `llm` and the model's reason in its evidence

#### Scenario: Ordinary business address
- **WHEN** a clean invoice's vendor address is an ordinary commercial street address
- **THEN** the LLM judges it plausible and no `SUSPICIOUS_ADDRESS` finding is raised

#### Scenario: No vendor address
- **WHEN** an invoice has no vendor address
- **THEN** no address assessment is requested and no `SUSPICIOUS_ADDRESS` finding is raised

#### Scenario: Assessment cannot be skipped
- **WHEN** the validation LLM finishes its tool loop without asking about the address
- **THEN** the address assessment still runs and its verdict is applied

#### Scenario: Assessment cannot clear a rule finding
- **WHEN** the LLM judges an address plausible on an invoice that also has a CRITICAL rule finding
- **THEN** the CRITICAL finding stands and the outcome is unchanged
