## Purpose

Keeps one canonical identity per payee, with its names, aliases, and remit-to addresses, and a ledger of every invoice received for it. Invoices from one payee can then be totalled over a rolling window, even when they arrive under different vendor names at the same address.

## ADDED Requirements

### Requirement: Payee identities
The system SHALL store each payee once, with a canonical name, its normalized names and aliases, and its normalized remit-to addresses. Normalization SHALL ignore case, punctuation, repeated spaces, and common business suffixes and street abbreviations, so trivially different spellings compare equal. The approved-vendor list SHALL stay separate from payee identities.

#### Scenario: Spelling variants normalize together
- **WHEN** "Northwind Fabrication, LLC" and "NORTHWIND FABRICATION LLC" are normalized
- **THEN** they produce the same normalized name

#### Scenario: Address abbreviations normalize together
- **WHEN** "2200 Industrial Parkway, Columbus OH 43215" and "2200 Industrial Pkwy., Columbus, OH 43215" are normalized
- **THEN** they produce the same normalized address

### Requirement: Resolving an invoice to its payees
An invoice SHALL resolve to every payee whose normalized name or alias matches the vendor name, or whose normalized address matches the vendor address. If none match, a new payee SHALL be created from the invoice's vendor name and address. An invoice with neither a vendor name nor a vendor address SHALL resolve to no payee.

#### Scenario: Same name
- **WHEN** an invoice from "Northwind Fabrication LLC" arrives and that payee exists
- **THEN** it resolves to that payee

#### Scenario: Different name, same address
- **WHEN** an invoice from "HPS Industrial Partners" lists "88 Harbor View Rd, Unit 4, Tacoma, WA 98402", the address already recorded for payee Harbor Point Supply Co.
- **THEN** it resolves to both the HPS Industrial Partners payee and the Harbor Point Supply Co. payee

#### Scenario: New vendor
- **WHEN** an invoice from a vendor whose name and address match no payee arrives
- **THEN** a new payee is created with that name and address and the invoice resolves to it

#### Scenario: No identity
- **WHEN** an invoice with an empty vendor name and no address arrives (INV-1009)
- **THEN** it resolves to no payee and no payee total is computed for it

### Requirement: Learning addresses and names
When an invoice resolves to a payee by name, the system SHALL record the invoice's address for that payee if it is new. When it resolves by address only, the system SHALL record the vendor name as an alias of a payee created for that name, keeping the link to the address-matched payee.

#### Scenario: Address learned from an invoice
- **WHEN** the first invoice from Harbor Point Supply Co. lists "88 Harbor View Rd, Unit 4, Tacoma, WA 98402"
- **THEN** that address is recorded for the Harbor Point Supply Co. payee

### Requirement: Invoice-to-payee ledger
Every processed invoice that resolves to a payee SHALL be recorded against each payee it resolves to, with the run, invoice number, revision, vendor name, vendor address, invoice date (or upload date when the invoice has none), USD total, and final outcome. This SHALL include rejected invoices and duplicate copies. Recording SHALL happen when the run reaches disposition, and the recorded outcome SHALL be updated when it changes later.

#### Scenario: Rejected invoice recorded
- **WHEN** an invoice is rejected for exceeding stock
- **THEN** it is recorded against its payee with outcome Rejected and its USD total

#### Scenario: Outcome updated
- **WHEN** an invoice recorded as Awaiting review is later approved and paid
- **THEN** its recorded outcome becomes Paid

### Requirement: Rolling cumulative payee total
For an invoice, the payee total SHALL be the largest sum of the invoices of all its resolved payees that are dated within any span of `PAYEE_WINDOW_DAYS` (default 30) consecutive days that includes the invoice's own date. The sum SHALL include the invoice itself. Each invoice number SHALL count once, at the total of its latest revision, and duplicate copies and superseded originals SHALL NOT add to it. Rejected invoices SHALL count.

#### Scenario: Split invoices summed
- **WHEN** Northwind Fabrication LLC has INV-1018 ($9,750.00, Feb 2) and INV-1019 ($9,500.00, Feb 9) is being checked
- **THEN** the payee total is $19,250.00 over INV-1018 and INV-1019

#### Scenario: Duplicate copies count once
- **WHEN** invoice_1012.pdf and invoice_1012.txt (both INV-1012, $9,975.00) are recorded for QuickShip Distributers
- **THEN** the payee total is $9,975.00

#### Scenario: Revision counts at its latest total
- **WHEN** INV-1004 ($1,890.00) and its revision R1 ($5,940.00) are recorded for Precision Parts Ltd.
- **THEN** the payee total is $5,940.00

#### Scenario: Outside the window
- **WHEN** a payee's two invoices are dated 45 days apart
- **THEN** no 30-day span holds both and the payee total for each is its own amount

#### Scenario: Order independent
- **WHEN** an invoice dated Feb 10 is processed before one from the same payee dated Feb 5
- **THEN** the later-processed Feb 5 invoice's payee total still includes the Feb 10 invoice
