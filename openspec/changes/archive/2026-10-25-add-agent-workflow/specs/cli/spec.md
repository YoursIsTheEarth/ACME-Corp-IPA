# Spec Delta

## Purpose

Gives operators and reviewers a terminal entry point to process invoice files, decide held invoices, run payment batches, and replay the audit trail of any run, matching the case README's `python main.py --invoice_path=...` contract.

## ADDED Requirements

### Requirement: Process a single invoice
`python main.py --invoice_path=<file>` SHALL run the file through the agent workflow and print the stage progress, the findings with severity, and the final outcome with its rationale (F18). The command SHALL exit 0 when the run reaches a disposition, whatever the outcome.

#### Scenario: README command
- **WHEN** a user runs `python main.py --invoice_path=data/invoices/invoice_1001.txt`
- **THEN** the terminal shows each stage completing, no findings, outcome APPROVE (queued for payment), and the `run_id`, and the exit code is 0

#### Scenario: Missing file
- **WHEN** the path does not exist
- **THEN** the command prints a clear error naming the path and exits non-zero without creating a run

### Requirement: Process a folder
`--batch <dir>` SHALL process every supported file in the folder in sorted filename order, one run per file, and print a results table with file, invoice number, vendor, amount (USD), outcome, and key finding codes.

#### Scenario: Batch the provided invoices
- **WHEN** a user runs `python main.py --batch data/invoices --provider offline`
- **THEN** 20 runs are created in sorted filename order and the results table lists all 20 with their outcomes

### Requirement: Provider override
`--provider grok|claude|offline` SHALL override the configured LLM provider for that command only. An invalid value SHALL be rejected before any run starts.

#### Scenario: Offline without keys
- **WHEN** no API keys are set and the user passes `--provider offline`
- **THEN** the command runs to completion

#### Scenario: Missing key for chosen provider
- **WHEN** the user passes `--provider grok` with no `XAI_API_KEY` set
- **THEN** the command stops before processing with a message naming the missing key

### Requirement: Machine-readable output
`--json` SHALL print one JSON object per run (run_id, file, invoice_number, vendor, total_usd, outcome, findings with code and severity, decided_by) instead of the formatted output, with logs kept off stdout.

#### Scenario: JSON for one file
- **WHEN** a user runs `python main.py --invoice_path=data/invoices/invoice_1002.txt --json`
- **THEN** stdout parses as JSON with outcome REJECT and a finding with code `STOCK_EXCEEDED`

### Requirement: Payment batch commands
`--pay` SHALL run one payment batch after processing finishes, and `python main.py payments run` SHALL run one batch on demand. Both SHALL print the batch ID, rows paid, total paid, and failures. CLI batches SHALL record `pay_all` as the trigger and `cli` as released_by unless `--released-by <name>` (1–50 characters) is given.

#### Scenario: Process and pay
- **WHEN** a user runs `python main.py --batch data/invoices --provider offline --pay`
- **THEN** after all 20 runs finish a single batch pays 7 rows, and the summary prints the total paid

#### Scenario: Nothing queued
- **WHEN** `python main.py payments run` runs with an empty payment queue
- **THEN** it prints that nothing is queued and makes no payments

### Requirement: Review held invoices from the terminal
`python main.py review` SHALL list invoices awaiting review with run_id, invoice number, vendor, amount, why held, and AI recommendation. `python main.py review <run_id> --decision approve|reject --reviewer <name> --rationale <text>` SHALL resume that run with the decision (F17). The reviewer name SHALL be 1–50 characters after trimming and the rationale at least 15 characters.

#### Scenario: List held invoices
- **WHEN** the golden batch has run and a user runs `python main.py review`
- **THEN** INV-1010 is listed with `PRICE_VARIANCE` and the AI recommendation

#### Scenario: Approve a held invoice
- **WHEN** a user runs `python main.py review <run_id of INV-1010> --decision approve --reviewer "Dana" --rationale "Rush pricing agreed by procurement"`
- **THEN** the run resumes, INV-1010 is added to the payment queue, and the audit records Dana as the decider

#### Scenario: Invalid reviewer input
- **WHEN** the reviewer name is blank after trimming or the rationale is shorter than 15 characters
- **THEN** the command refuses with a message stating the rule and the run stays awaiting review

#### Scenario: Run not awaiting review
- **WHEN** the run_id is not awaiting review
- **THEN** the command exits non-zero with a message that the invoice is no longer awaiting review

### Requirement: Replay a run's audit trail
`python main.py --explain <run_id>` SHALL print the run's trace from `audit_log` in order: extraction notes and retries, findings with evidence, rules fired, each AI VP draft and Critic response with provider and model, any reviewer decision, and the disposition (F19).

#### Scenario: Explain a rejected run
- **WHEN** a user runs `--explain` on the run for `invoice_1003.txt`
- **THEN** the output shows `ZERO_STOCK`, `INVALID_DUE_DATE`, and `FRAUD_SUSPECTED` with evidence, the rule that forced REJECT, and the rejection record

#### Scenario: Unknown run
- **WHEN** the run_id does not exist
- **THEN** the command exits non-zero with a "run not found" message

### Requirement: Batch summary report (P1)
After a `--batch` run, the CLI SHALL print and write `reports/summary.md` with counts per outcome, dollars queued, dollars paid, dollars blocked (rejected or held), and duplicates caught (F31).

#### Scenario: Summary after golden batch with pay
- **WHEN** `python main.py --batch data/invoices --provider offline --pay` finishes
- **THEN** `reports/summary.md` shows 7 paid, 1 superseded, 1 held, 11 rejected, and 3 duplicates caught
