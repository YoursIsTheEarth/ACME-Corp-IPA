## MODIFIED Requirements

### Requirement: Invalid due dates are marked, missing ones left empty (F6)
A due date that is relative ("yesterday", "today", "ASAP") or can't be parsed SHALL leave `due_date` empty and keep the source text in `due_date_raw`. The source text SHALL be the extracted `due_date` when it is not blank, and otherwise the extracted `due_date_raw`. An absent or null due date SHALL leave both empty. Normalization SHALL NOT emit due-date findings; `invoice-validation` is the single owner of `INVALID_DUE_DATE` and `MISSING_DUE_DATE`.

#### Scenario: Relative due date
- **WHEN** `invoice_1003.txt`, with due date "yesterday", is normalized
- **THEN** `due_date` is empty, `due_date_raw` is "yesterday", and normalization emits no finding

#### Scenario: Worded due date in due_date_raw
- **WHEN** the extracted invoice has a blank `due_date` and `due_date_raw` "yesterday"
- **THEN** `due_date` is empty and `due_date_raw` is "yesterday"

#### Scenario: Null due date
- **WHEN** `invoice_1009.json`, with `"due_date": null`, is normalized
- **THEN** `due_date` and `due_date_raw` are both empty and normalization emits no finding
