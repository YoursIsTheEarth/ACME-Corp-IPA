# invoice-approval Specification

## Purpose
Decides each validated invoice's outcome (APPROVE, REJECT, or NEEDS_REVIEW). A deterministic rules engine sets the floor, and an AI VP with a Critic explains the outcome or tightens it. The decision is traceable to the rules, the findings, and the LLM rationale.

## Requirements

### Requirement: Rules engine returns a floor outcome (F14)
The rules engine SHALL take an invoice, its findings, and its revision context. It SHALL return a floor outcome (APPROVE, REJECT, or NEEDS_REVIEW), the list of rules that fired, a fraud flag, and whether VP scrutiny is required. Its output SHALL be the same every time for the same inputs, and it SHALL make no LLM or database calls.

#### Scenario: Deterministic output
- **WHEN** the rules engine is called twice with the same invoice, findings, and revision context
- **THEN** both calls return the same outcome and the same rules, in the same order

### Requirement: Critical findings force rejection (F14)
Any CRITICAL finding SHALL produce floor REJECT, with a fired rule per CRITICAL code.

#### Scenario: Stock exceeded
- **WHEN** INV-1002 has a CRITICAL `STOCK_EXCEEDED` finding
- **THEN** the floor outcome is REJECT

#### Scenario: Duplicate
- **WHEN** invoice_1011.txt has a CRITICAL `DUPLICATE` finding
- **THEN** the floor outcome is REJECT

### Requirement: Fraud score forces rejection with a flag (F14)
A `FRAUD_SUSPECTED` finding SHALL produce floor REJECT with the fraud flag set.

#### Scenario: Fraudulent invoice
- **WHEN** INV-1003 has `FRAUD_SUSPECTED`
- **THEN** the floor outcome is REJECT and the fraud flag is true

### Requirement: Warnings require human review (F14)
If there is no CRITICAL finding and no fraud flag, any WARNING finding SHALL produce floor NEEDS_REVIEW.

#### Scenario: Price variance
- **WHEN** INV-1010's only blocking finding is WARNING `PRICE_VARIANCE`
- **THEN** the floor outcome is NEEDS_REVIEW

#### Scenario: Paid invoice revised downward
- **WHEN** a revision has WARNING `REVISION_CREDIT_DUE`
- **THEN** the floor outcome is NEEDS_REVIEW

### Requirement: Threshold routing for clean invoices (F14)
An invoice with no CRITICAL or WARNING findings SHALL get floor APPROVE. If its USD total is greater than $10,000.00, VP scrutiny SHALL be required. If its total is $10,000.00 or less, the result SHALL be auto-approval. INFO findings SHALL NOT block approval.

#### Scenario: Auto-approve at or below the threshold
- **WHEN** INV-1012 totals $9,975.00 and its only finding is INFO `NEAR_THRESHOLD`
- **THEN** the floor outcome is APPROVE and VP scrutiny is not required

#### Scenario: Exactly $10,000.00
- **WHEN** a clean invoice totals exactly $10,000.00
- **THEN** VP scrutiny is not required

#### Scenario: Over the threshold
- **WHEN** a clean invoice totals $12,000.00
- **THEN** the floor outcome is APPROVE and VP scrutiny is required

#### Scenario: Revision judged as a new invoice
- **WHEN** INV-1004 R1 totals $5,940.00 and its only finding is INFO `REVISION`
- **THEN** the floor outcome is APPROVE without VP scrutiny

### Requirement: Outcome can only be tightened (F15)
The final outcome SHALL be the stricter of the rules-engine floor and the LLM's outcome, using the order REJECT > NEEDS_REVIEW > APPROVE. If the LLM proposes a looser outcome, the floor SHALL apply and the override attempt SHALL be recorded in the trace.

#### Scenario: LLM tries to approve a rejected invoice
- **WHEN** the floor is REJECT and the LLM draft says APPROVE
- **THEN** the final outcome is REJECT and the trace records the clamped draft

#### Scenario: LLM tightens to review
- **WHEN** the floor is APPROVE with VP scrutiny and the LLM draft says NEEDS_REVIEW
- **THEN** the final outcome is NEEDS_REVIEW

### Requirement: AI VP rationale for every decision (F15)
Every final `Decision` SHALL include a rationale written by the configured LLM, the rules applied, and a confidence. For floor REJECT the rationale SHALL explain the fired rules and findings. For auto-approval it SHALL be one line. For NEEDS_REVIEW it SHALL include a recommended outcome, which the Elevated Review page shows.

#### Scenario: Rejection explained
- **WHEN** INV-1016 is rejected for `UNKNOWN_ITEM`
- **THEN** the decision rationale names WidgetC and the fired rule

#### Scenario: Review recommendation
- **WHEN** INV-1010 is held for review
- **THEN** the decision includes the AI's recommended outcome and a one-line reason

### Requirement: Critic loop on VP scrutiny (F15)
When VP scrutiny is required, the Critic SHALL check the draft against the policy and evidence, and Approval SHALL revise until the Critic passes or 2 revision rounds are used. If the Critic still fails after round 2, the outcome SHALL be NEEDS_REVIEW. Each draft and critique SHALL be appended to the trace with provider and model.

#### Scenario: Critic passes the first draft
- **WHEN** an invoice over $10,000 with no findings gets a draft that cites the policy correctly
- **THEN** the Critic passes and the draft becomes the decision after 1 round

#### Scenario: Critic never passes
- **WHEN** the Critic rejects the original draft and both revisions
- **THEN** the final outcome is NEEDS_REVIEW and all 3 drafts and critiques are in the trace

#### Scenario: Critic cannot loosen
- **WHEN** a critique suggests APPROVE but the draft says NEEDS_REVIEW
- **THEN** the outcome stays NEEDS_REVIEW

### Requirement: Decision provenance
Each decision SHALL record who decided it: `Auto (rules)` when no LLM changed or reviewed the outcome, or `AI VP` with the provider and model when the VP path ran.

#### Scenario: Auto-approved invoice
- **WHEN** INV-1001 is approved without VP scrutiny
- **THEN** the decision records "Auto (rules)"

### Requirement: Approval does not move money
Approval SHALL produce only a `Decision`. It SHALL NOT call the payment function or write to the payment ledger.

#### Scenario: Approved invoice
- **WHEN** INV-1001 gets final outcome APPROVE
- **THEN** no payment row is created by the approval step
