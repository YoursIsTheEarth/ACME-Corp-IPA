## MODIFIED Requirements

### Requirement: Payment batch commands
`--pay` SHALL run one payment batch after processing finishes, and `python main.py payments run` SHALL run one batch on demand. Both SHALL pay whatever is payable in either payment mode and SHALL print the batch ID, rows paid, total paid, and failures. CLI batches SHALL record `pay_all` as the trigger and `cli` as released_by unless `--released-by <name>` (1–50 characters) is given. `payments run` makes no LLM call and SHALL work without an LLM key.

#### Scenario: Process and pay
- **WHEN** payment delay is on and a user with an LLM key configured runs `python main.py --batch data/invoices --pay`
- **THEN** after all 20 runs finish a single batch pays 7 rows, and the summary prints the total paid

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
- **THEN** `reports/summary.md` shows 7 paid, 1 superseded, 1 held, 11 rejected, and 3 duplicates caught

#### Scenario: Summary after golden batch with delay off
- **WHEN** payment delay is off and `python main.py --batch data/invoices` finishes with an LLM key configured
- **THEN** `reports/summary.md` shows 7 paid, 1 revised, 0 superseded, 1 held, 11 rejected, 3 duplicates caught, and $37,620.00 paid

## ADDED Requirements

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

#### Scenario: Turn on delayed payments
- **WHEN** a user runs `python main.py admin set --delay-payments on --by Dana`
- **THEN** the settings are saved with delay on and the other values unchanged, and `admin show` prints delay on, last saved by Dana

#### Scenario: Invalid timezone
- **WHEN** a user runs `python main.py admin set --end-of-day-timezone Mars/Olympus --by Dana`
- **THEN** the command exits non-zero naming the bad timezone and nothing is saved
