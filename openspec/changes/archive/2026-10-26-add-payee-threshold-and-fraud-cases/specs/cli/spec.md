## MODIFIED Requirements

### Requirement: Process a folder
`--batch <dir>` SHALL process every supported file in the folder in sorted filename order, one run per file, and print a results table with file, invoice number, vendor, amount (USD), outcome, and key finding codes.

#### Scenario: Batch the provided invoices
- **WHEN** a user with an LLM key configured runs `python main.py --batch data/invoices`
- **THEN** 26 runs are created in sorted filename order and the results table lists all 26 with their outcomes

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

### Requirement: Batch summary report (P1)
After a `--batch` run, the CLI SHALL print and write `reports/summary.md` with counts per outcome, dollars queued, dollars paid, dollars blocked (rejected or held), and duplicates caught (F31).

#### Scenario: Summary after golden batch with pay
- **WHEN** payment delay is on and `python main.py --batch data/invoices --pay` finishes with an LLM key configured
- **THEN** `reports/summary.md` shows 7 paid, 1 superseded, 6 held, 12 rejected, and 3 duplicates caught

#### Scenario: Summary after golden batch with delay off
- **WHEN** payment delay is off and `python main.py --batch data/invoices` finishes with an LLM key configured
- **THEN** `reports/summary.md` shows 9 paid, 1 revised, 0 superseded, 4 held, 12 rejected, 3 duplicates caught, and $53,370.00 paid
