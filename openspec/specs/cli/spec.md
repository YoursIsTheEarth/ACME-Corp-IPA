# cli Specification

## Purpose
Gives operators and reviewers a terminal entry point to process invoice files, decide held invoices, run payment batches, and replay the audit trail of any run, matching the case README's `python main.py --invoice_path=...` contract.

## Requirements

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
- **WHEN** a user with an LLM key configured runs `python main.py --batch data/invoices`
- **THEN** 26 runs are created in sorted filename order and the results table lists all 26 with their outcomes

### Requirement: Machine-readable output
`--json` SHALL print one JSON object per run (run_id, file, invoice_number, vendor, total_usd, outcome, findings with code and severity, decided_by) instead of the formatted output, with logs kept off stdout.

#### Scenario: JSON for one file
- **WHEN** a user runs `python main.py --invoice_path=data/invoices/invoice_1002.txt --json`
- **THEN** stdout parses as JSON with outcome REJECT and a finding with code `STOCK_EXCEEDED`

### Requirement: Payment batch commands
`--pay` SHALL run one payment batch after processing finishes, and `python main.py payments run` SHALL run one batch on demand. Both SHALL pay whatever is payable in either payment mode and SHALL print the batch ID, rows paid, total paid, and failures. CLI batches SHALL record `pay_all` as the trigger and `cli` as released_by unless `--released-by <name>` (1–50 characters) is given. `payments run` makes no LLM call and SHALL work without an LLM key.

#### Scenario: Process and pay
- **WHEN** payment delay is on and a user with an LLM key configured runs `python main.py --batch data/invoices --pay`
- **THEN** after all 26 runs finish a single batch pays 7 rows, and the summary prints the total paid

#### Scenario: Process and pay with delay off
- **WHEN** payment delay is off and a user with an LLM key configured runs `python main.py --batch data/invoices --pay`
- **THEN** each approved invoice is paid as its run finishes, and the `--pay` batch prints that nothing is queued

#### Scenario: Nothing queued
- **WHEN** `python main.py payments run` runs with an empty payment queue
- **THEN** it prints that nothing is queued and makes no payments

#### Scenario: Paying queued rows without a key
- **WHEN** no LLM key is set and `python main.py payments run` runs with rows queued
- **THEN** the batch runs and pays the queued rows

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
- **WHEN** payment delay is on and `python main.py --batch data/invoices --pay` finishes with an LLM key configured
- **THEN** `reports/summary.md` shows 7 paid, 1 superseded, 6 held, 12 rejected, and 3 duplicates caught

#### Scenario: Summary after golden batch with delay off
- **WHEN** payment delay is off and `python main.py --batch data/invoices` finishes with an LLM key configured
- **THEN** `reports/summary.md` shows 9 paid, 1 revised, 0 superseded, 4 held, 12 rejected, 3 duplicates caught, and $53,370.00 paid

### Requirement: Provider override without offline
`--provider grok|claude` SHALL override the configured LLM provider for that command only. Any other value, including `offline`, SHALL be rejected before any run starts with a message naming `grok` and `claude` as the valid values.

#### Scenario: Offline rejected
- **WHEN** the user passes `--provider offline`
- **THEN** the command exits non-zero before any run starts, naming `grok` and `claude` as the valid values

#### Scenario: Missing key for chosen provider
- **WHEN** the user passes `--provider grok` with no `XAI_API_KEY` set
- **THEN** the command stops before processing with the no-LLM-token message naming `XAI_API_KEY`

### Requirement: Processing refuses without an LLM key
`--invoice_path` and `--batch` SHALL check the LLM key status before creating any run. When a needed key is missing, they SHALL exit non-zero without creating a run and print that no LLM token is provided, which variable to set (`XAI_API_KEY` for Grok, `ANTHROPIC_API_KEY` for Claude), and that invoices cannot be processed without it. Commands that make no LLM call (`--explain`, `review`, `payments run`) SHALL still run without a key.

#### Scenario: README command without a key
- **WHEN** no API key is set and a user runs `python main.py --invoice_path=data/invoices/invoice_1001.txt`
- **THEN** the command exits non-zero, creates no run, and prints that no LLM token is provided, that `XAI_API_KEY` must be set for Grok, and that invoices cannot be processed without it

#### Scenario: Claude selected without its key
- **WHEN** `LLM_PROVIDER=claude`, `ANTHROPIC_API_KEY` is unset, and a user runs `--batch data/invoices`
- **THEN** the command exits non-zero before any run starts with the message naming `ANTHROPIC_API_KEY`

#### Scenario: JSON output without a key
- **WHEN** no API key is set and a user runs `python main.py --invoice_path=data/invoices/invoice_1001.txt --json`
- **THEN** stdout parses as a JSON error object carrying the same message and the missing variable name, and the exit code is non-zero

#### Scenario: Explain works without a key
- **WHEN** no API key is set and a user runs `python main.py --explain <run_id>` for an existing run
- **THEN** the run's audit trail is printed and the command exits 0

### Requirement: Immediate payment during CLI processing
CLI processing SHALL follow the stored payment timing. With delay off, each approved invoice SHALL be paid by an `immediate` batch before its result is printed, and the result SHALL show the payment ID. With delay on, approved invoices SHALL be printed as queued for payment.

#### Scenario: Single invoice paid at approval
- **WHEN** payment delay is off and a user runs `python main.py --invoice_path=data/invoices/invoice_1001.txt`
- **THEN** the output shows outcome APPROVE, final status Paid, and a payment ID

#### Scenario: Single invoice queued with delay on
- **WHEN** payment delay is on and the same command runs
- **THEN** the output shows the invoice queued for payment and no payment ID

### Requirement: Show and change payment timing from the terminal
`python main.py admin show` SHALL print the current payment timing and who last saved it. `python main.py admin set` SHALL accept `--delay-payments`, `--pay-at-end-of-day`, `--end-of-day-time HH:MM`, `--end-of-day-timezone <IANA>`, `--pay-when-queue-empty` (each with `on` or `off` where boolean) and a required `--by <name>` (1–50 characters). It SHALL validate like the API, save, audit the change, and exit non-zero with a message on invalid input. Neither command needs an LLM key.

#### Scenario: Turn on immediate payments
- **WHEN** a user runs `python main.py admin set --delay-payments off --by Dana`
- **THEN** the settings are saved with delay off and the other values unchanged, and `admin show` prints delay off, last saved by Dana

#### Scenario: Invalid timezone
- **WHEN** a user runs `python main.py admin set --end-of-day-timezone Mars/Olympus --by Dana`
- **THEN** the command exits non-zero naming the bad timezone and nothing is saved
