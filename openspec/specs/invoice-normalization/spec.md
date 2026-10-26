# invoice-normalization Specification

## Purpose
Converts an extracted invoice into the canonical `Invoice` that validation, approval, and payment rely on: resolved SKUs, cleaned dates and money, a normalized invoice number, and USD amounts. Validation then compares like with like across every source format.

## Requirements

### Requirement: SKU resolution by alias, then fuzzy match (F5)
Each line item's raw name SHALL resolve to an inventory SKU in this order: an exact match on SKU or alias, ignoring case, spaces, and punctuation; then an `item_aliases` lookup; then a fuzzy match against SKUs and aliases. A fuzzy match SHALL be accepted only at a similarity score of 90 or above out of 100.

#### Scenario: Spacing variants resolve through aliases
- **WHEN** the line items of `invoice_1012.pdf` ("Widget A", "WidgetB", "Gadget X") are normalized
- **THEN** their SKUs are WidgetA, WidgetB, and GadgetX

#### Scenario: Zero-stock SKU still resolves
- **WHEN** a line item named "FakeItem" is normalized
- **THEN** its SKU is FakeItem; flagging zero stock is left to validation

#### Scenario: Qualifier text does not block a match
- **WHEN** a line item has raw name "WidgetA" and note "rush order"
- **THEN** its SKU is WidgetA

### Requirement: Unmatched items stay unknown (F5)
A raw name with no match at or above the threshold SHALL be left with no SKU, and its raw name SHALL be kept. Normalization SHALL NOT substitute the nearest SKU below the threshold, and SHALL NOT emit the unknown-item finding; that finding belongs to validation.

#### Scenario: Products not in inventory
- **WHEN** "SuperGizmo" and "MegaSprocket" from `invoice_1008.txt` are normalized
- **THEN** both line items have no SKU and keep their raw names

#### Scenario: Near-miss below the threshold
- **WHEN** "WidgetC" from `invoice_1016.json` is normalized
- **THEN** it has no SKU, and it is not mapped to WidgetA

#### Scenario: Lookalike character
- **WHEN** a raw name is "WidgetА", ending in a Cyrillic "А"
- **THEN** it has no SKU

### Requirement: OCR digit repair in dates and money (F6)
In date and money values, the letter O or o appearing next to a digit, or inside a run of digits, SHALL be read as zero. Repairs SHALL be recorded in the run's audit trail with the original and repaired text. Free-text fields such as vendor name and notes SHALL NOT be altered.

#### Scenario: OCR noise in the year and in an amount
- **WHEN** `invoice_1012.pdf`, with date "26-Jan-2O26" and line amount "$3,500.O0", is normalized
- **THEN** the invoice date is 2026-01-26, the line amount is 3500.00, and the audit trail records both repairs

#### Scenario: Words with the letter O untouched
- **WHEN** a vendor name "Sono Corp" is normalized
- **THEN** the vendor name is unchanged

### Requirement: Date parsing (F6)
Invoice and due dates SHALL be parsed into calendar dates from ISO (`2026-01-30`), `MM/DD/YYYY` (read as US month first), `Jan 30 2026`, `January 27, 2026`, and `26-Jan-2026` forms.

#### Scenario: US slash dates
- **WHEN** `invoice_1007.csv`, with date "01/28/2026" and due date "02/28/2026", is normalized
- **THEN** the invoice date is 2026-01-28 and the due date is 2026-02-28

#### Scenario: Month-name dates
- **WHEN** `invoice_1002.txt` ("Jan 30 2026") and `invoice_1010.txt` ("January 27, 2026", "February 26, 2026") are normalized
- **THEN** the dates are 2026-01-30, 2026-01-27, and 2026-02-26

### Requirement: Invalid due dates are marked, missing ones left empty (F6)
A due date that is relative ("yesterday", "today", "ASAP") or can't be parsed SHALL leave `due_date` empty and keep the source text in `due_date_raw`. An absent or null due date SHALL leave both empty. Normalization SHALL NOT emit due-date findings; `invoice-validation` is the single owner of `INVALID_DUE_DATE` and `MISSING_DUE_DATE`.

#### Scenario: Relative due date
- **WHEN** `invoice_1003.txt`, with due date "yesterday", is normalized
- **THEN** `due_date` is empty, `due_date_raw` is "yesterday", and normalization emits no finding

#### Scenario: Null due date
- **WHEN** `invoice_1009.json`, with `"due_date": null`, is normalized
- **THEN** `due_date` and `due_date_raw` are both empty and normalization emits no finding

### Requirement: Money parsing (F6)
Money values SHALL be parsed from strings with currency symbols, thousands separators, and surrounding spaces into decimal amounts rounded to cents. Negative values SHALL be kept, not corrected.

#### Scenario: Formatted amount
- **WHEN** the value "$15,000.00" is normalized
- **THEN** the amount is 15000.00

#### Scenario: Negative total kept
- **WHEN** `invoice_1009.json`, with total -250.00, is normalized
- **THEN** the total remains -250.00

### Requirement: Invoice number and revision normalization (F6)
Invoice numbers SHALL be normalized to `INV-<digits>`, whatever the prefix, spacing, `#`, or missing prefix. A revision label SHALL be upper-cased (`r1` → `R1`). An invoice without a revision label is the original.

#### Scenario: Bare number and spaced prefix
- **WHEN** `invoice_1002.txt` ("Inv #: 1002") and `invoice_1012.txt` ("INV NO: INV 1012") are normalized
- **THEN** their invoice numbers are `INV-1002` and `INV-1012`

#### Scenario: Same invoice in two formats normalizes identically
- **WHEN** `invoice_1011.pdf` and `invoice_1011.txt` are both normalized
- **THEN** both have invoice number `INV-1011`, the same vendor name, and the same total, so duplicate detection can match them

### Requirement: Deterministic first, LLM only as a fallback (F5, F6)
Normalization SHALL resolve SKUs and dates deterministically. It SHALL call the LLM only for a SKU or date the deterministic steps can't resolve. An LLM-proposed SKU SHALL be accepted only if it exists in `inventory`; otherwise the item stays unknown.

#### Scenario: Clean invoice needs no LLM
- **WHEN** `invoice_1015.csv` is normalized
- **THEN** no LLM call is recorded for agent `normalizer`

#### Scenario: LLM proposes a non-existent SKU
- **WHEN** the LLM fallback suggests "SuperGizmoPro" for "SuperGizmo"
- **THEN** the line item stays without a SKU

### Requirement: Currency conversion to USD (F7, P1)
A non-USD invoice SHALL be converted to USD at the fixed rate configured for its currency. The original currency and amounts SHALL be kept alongside the USD amounts, and an INFO `CURRENCY_CONVERTED` finding SHALL record the rate and both totals. An invoice with no currency stated SHALL be treated as USD.

#### Scenario: Euro invoice
- **WHEN** `invoice_1014.xml` (EUR, total 4125.00) is normalized with a configured EUR rate
- **THEN** the USD total equals 4125.00 × the rate rounded to cents (4455.00 at the default 1.08), `original_currency` is EUR and `original_total` is 4125.00, and there is an INFO `CURRENCY_CONVERTED` finding

#### Scenario: USD invoice
- **WHEN** a USD invoice is normalized
- **THEN** its USD total equals its total and there is no `CURRENCY_CONVERTED` finding

### Requirement: Unknown currency fails closed (F7, P1)
A currency with no configured rate SHALL NOT be converted or treated as USD. The system SHALL emit a WARNING `CURRENCY_UNSUPPORTED` finding naming the currency, so the invoice is held for review rather than paid.

#### Scenario: Currency without a rate
- **WHEN** an invoice in `GBP` is normalized and no GBP rate is configured
- **THEN** there is a WARNING `CURRENCY_UNSUPPORTED` finding with evidence `GBP`, and no USD total is filled in
