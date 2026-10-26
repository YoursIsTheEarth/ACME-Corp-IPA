## MODIFIED Requirements

### Requirement: Process a folder
`--batch <dir>` SHALL process every supported file in the folder in sorted filename order, one run per file, and print a results table with file, invoice number, vendor, amount (USD), outcome, and key finding codes.

#### Scenario: Batch the provided invoices
- **WHEN** a user with an LLM key configured runs `python main.py --batch data/invoices`
- **THEN** 20 runs are created in sorted filename order and the results table lists all 20 with their outcomes

### Requirement: Payment batch commands
`--pay` SHALL run one payment batch after processing finishes, and `python main.py payments run` SHALL run one batch on demand. Both SHALL print the batch ID, rows paid, total paid, and failures. CLI batches SHALL record `pay_all` as the trigger and `cli` as released_by unless `--released-by <name>` (1–50 characters) is given. `payments run` makes no LLM call and SHALL work without an LLM key.

#### Scenario: Process and pay
- **WHEN** a user with an LLM key configured runs `python main.py --batch data/invoices --pay`
- **THEN** after all 20 runs finish a single batch pays 7 rows, and the summary prints the total paid

#### Scenario: Nothing queued
- **WHEN** `python main.py payments run` runs with an empty payment queue
- **THEN** it prints that nothing is queued and makes no payments

#### Scenario: Paying queued rows without a key
- **WHEN** no LLM key is set and `python main.py payments run` runs with rows queued
- **THEN** the batch runs and pays the queued rows

### Requirement: Batch summary report (P1)
After a `--batch` run, the CLI SHALL print and write `reports/summary.md` with counts per outcome, dollars queued, dollars paid, dollars blocked (rejected or held), and duplicates caught (F31).

#### Scenario: Summary after golden batch with pay
- **WHEN** `python main.py --batch data/invoices --pay` finishes with an LLM key configured
- **THEN** `reports/summary.md` shows 7 paid, 1 superseded, 1 held, 11 rejected, and 3 duplicates caught

## REMOVED Requirements

### Requirement: Provider override
**Reason**: The `offline` provider value is removed, so the requirement's "Offline without keys" behavior no longer exists.
**Migration**: Replaced by "Provider override without offline"; pass `--provider grok` or `--provider claude` with the matching key set.

## ADDED Requirements

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
