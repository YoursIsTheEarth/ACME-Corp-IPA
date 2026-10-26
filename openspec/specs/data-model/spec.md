# data-model Specification

## Purpose
Defines the shared invoice domain models every agent exchanges and the single SQLite database, `acme.db`, that holds all persistent state, including its seed data.

## Requirements

### Requirement: Invoice domain models
The system SHALL represent invoices with validated models: `LineItem` (`sku`, `raw_name`, `quantity`, `unit_price`, `amount`, `note`) and `Invoice` (`invoice_number`, `revision`, `vendor_name`, `vendor_address`, `invoice_date`, `due_date`, `due_date_raw`, `currency`, `original_currency`, `original_total`, `line_items`, `subtotal`, `tax`, `shipping`, `total`, `payment_terms`, `notes`, `extraction_confidence`). Money values SHALL be exact decimals, not floats.

#### Scenario: Unparseable due date kept as text
- **WHEN** an invoice is built with no `due_date` and `due_date_raw` "yesterday"
- **THEN** it validates and keeps "yesterday" for validation to report

#### Scenario: Converted invoice keeps its source amounts
- **WHEN** a EUR invoice is converted to USD
- **THEN** `currency` is USD, `original_currency` is EUR, and `original_total` holds the EUR total

#### Scenario: Valid invoice accepted
- **WHEN** an invoice with a vendor, invoice number, line items, and totals is constructed
- **THEN** the model validates and money fields hold exact decimal values (e.g. 5000.00)

#### Scenario: Schema violation reported
- **WHEN** an `Invoice` is constructed with a non-numeric total
- **THEN** validation fails with an error message naming the offending field

#### Scenario: Missing optional fields allowed
- **WHEN** an invoice has no vendor name or no due date (as in INV-1009)
- **THEN** the model still validates so that downstream checks can raise findings instead of the system crashing

### Requirement: Findings, decisions, and critiques
The system SHALL model `Finding` (`code`, `severity`, `message`, `evidence`, `source`), `Decision` (`outcome`, `rationale`, `rules_applied`, `confidence`), and `Critique` (`passes`, `issues[]`, `suggested_outcome`). Severity SHALL be one of CRITICAL, WARNING, INFO; outcome SHALL be one of APPROVE, REJECT, NEEDS_REVIEW; source SHALL be `rule` or `llm`.

#### Scenario: Unknown severity rejected
- **WHEN** a `Finding` is created with severity "HIGH"
- **THEN** validation fails

#### Scenario: Decision outcome enumerated
- **WHEN** a `Decision` is created with outcome NEEDS_REVIEW
- **THEN** it validates and serializes the outcome as "NEEDS_REVIEW"

### Requirement: Finding code catalog
The system SHALL define one enumerated catalog of finding codes used verbatim across all stages, each with one canonical severity that rule-sourced findings SHALL use. The CRITICAL codes SHALL be `EXTRACTION_FAILED`, `UNKNOWN_ITEM`, `ZERO_STOCK`, `STOCK_EXCEEDED`, `INVALID_QUANTITY`, `MATH_MISMATCH`, `MISSING_VENDOR`, `DUPLICATE`, and `FRAUD_SUSPECTED`.

#### Scenario: Critical code
- **WHEN** the catalog is asked for the severity of `DUPLICATE`
- **THEN** it returns CRITICAL

### Requirement: Warning and info finding codes
The catalog's WARNING codes SHALL be `UNKNOWN_VENDOR`, `MISSING_DUE_DATE`, `INVALID_DUE_DATE`, `DUE_BEFORE_INVOICE_DATE`, `PRICE_VARIANCE`, `SUSPICIOUS_ADDRESS`, `REVISION_CREDIT_DUE`, `INVOICE_NUMBER_REUSED`, and `CURRENCY_UNSUPPORTED`. Its INFO codes SHALL be `REVISION`, `SUPERSEDED_BY_REVISION`, `NEAR_THRESHOLD`, and `CURRENCY_CONVERTED`.

#### Scenario: Info code
- **WHEN** the catalog is asked for the severity of `NEAR_THRESHOLD`
- **THEN** it returns INFO

#### Scenario: Canonical severity
- **WHEN** the catalog is asked for the severity of `CURRENCY_UNSUPPORTED`
- **THEN** it returns WARNING

#### Scenario: Codes serialize verbatim
- **WHEN** a finding with code `STOCK_EXCEEDED` is serialized to JSON
- **THEN** the JSON value is exactly "STOCK_EXCEEDED"

### Requirement: Workflow state object
The system SHALL model `InvoiceState` with `run_id`, `file_path`, `raw_text`, `extracted`, `invoice`, `findings`, `decision_draft`, `critique`, `decision`, `payment_result`, `trace[]`, and `retries`, and the state SHALL round-trip through JSON without loss so a paused run can be persisted and resumed.

#### Scenario: State round-trip
- **WHEN** an `InvoiceState` holding an invoice, two findings, and a decision is serialized to JSON and loaded back
- **THEN** the loaded state equals the original

### Requirement: Database schema
The system SHALL keep all persistent state in one SQLite file, `acme.db`, with tables `inventory` (`item` PK, `stock`, `unit_price`, `category`), `item_aliases`, `vendors`, `processed_invoices`, `payments` (unique `idempotency_key`), `audit_log`, `llm_calls`, `invoice_runs`, `review_decisions`, `payment_queue`, `payment_batches`, and `admin_settings`, with the columns listed in the design spec. `payment_batches.trigger` SHALL also accept `immediate`. Creating the schema SHALL be idempotent.

#### Scenario: Schema created on empty file
- **WHEN** schema creation runs against a missing `acme.db`
- **THEN** the file is created and contains all twelve tables

#### Scenario: Schema creation is repeatable
- **WHEN** schema creation runs a second time against an existing `acme.db`
- **THEN** no error occurs and existing rows are preserved

#### Scenario: Existing database gains the settings table
- **WHEN** schema creation runs against an `acme.db` created before `admin_settings` existed
- **THEN** the `admin_settings` table (`key` PK, `value`, `updated_by`, `updated_at`) is added, it is empty, and existing rows in every other table are preserved

#### Scenario: Payment idempotency enforced by the database
- **WHEN** two rows with the same `idempotency_key` are inserted into `payments`
- **THEN** the second insert fails

### Requirement: Seed command
The system SHALL provide `python -m acme.db seed`, which creates the schema and seeds `inventory` with WidgetA (15, $250.00), WidgetB (10, $500.00), GadgetX (5, $750.00), and FakeItem (0, no price); `item_aliases` with spacing variants (for example "Widget A" → WidgetA, "Gadget X" → GadgetX); and the vendor list below. Re-running seed SHALL leave the same seed rows, not duplicates.

#### Scenario: Seeded stock matches the case README
- **WHEN** `python -m acme.db seed` runs on a fresh checkout
- **THEN** `inventory` contains exactly WidgetA 15, WidgetB 10, GadgetX 5, FakeItem 0

#### Scenario: Seed is repeatable
- **WHEN** seed runs twice
- **THEN** each seed row exists once and run data in other tables is not deleted

#### Scenario: Unknown items absent
- **WHEN** the seeded inventory is queried for SuperGizmo, MegaSprocket, or WidgetC
- **THEN** no row is found

### Requirement: Vendor seed
Seed SHALL mark as approved: Widgets Inc., Precision Parts Ltd., Acme Industrial Supplies, Consolidated Materials Group, Summit Manufacturing Co., QuickShip Distributers (aliases "QuickShip Distributers (formerly FastShip Ltd.)" and "FastShip Ltd."), TechParts International, Reliable Components Inc., Gadgets Co., Global Supply Chain Partners, MegaWidgets Corp, and Atlas Industrial Supply. It SHALL NOT seed NoProd Industries or Fraudster LLC.

#### Scenario: Renamed vendor seeded with aliases
- **WHEN** the seeded `vendors` table is queried for "FastShip Ltd."
- **THEN** it resolves to the approved vendor QuickShip Distributers

#### Scenario: Unknown vendors absent
- **WHEN** the seeded `vendors` table is queried for NoProd Industries or Fraudster LLC
- **THEN** no approved row is found
