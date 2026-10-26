## MODIFIED Requirements

### Requirement: Fraud score forces rejection with a flag (F14)
A `FRAUD_SUSPECTED` or `PROMPT_INJECTION_SUSPECTED` finding at CRITICAL severity SHALL produce floor REJECT with the fraud flag set.

#### Scenario: Fraudulent invoice
- **WHEN** INV-1003 has `FRAUD_SUSPECTED`
- **THEN** the floor outcome is REJECT and the fraud flag is true

#### Scenario: Prompt injection
- **WHEN** INV-1017 has CRITICAL `PROMPT_INJECTION_SUSPECTED`
- **THEN** the floor outcome is REJECT, the fraud flag is true, and the rules applied include `CRITICAL_PROMPT_INJECTION_SUSPECTED`
- **AND** the AI VP's draft cannot change the outcome, whatever the invoice text says

#### Scenario: LLM-reported injection only
- **WHEN** an invoice's only injection finding is a WARNING `PROMPT_INJECTION_SUSPECTED` from the LLM
- **THEN** the floor outcome is NEEDS_REVIEW and the fraud flag is false
