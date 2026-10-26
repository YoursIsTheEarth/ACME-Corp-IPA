## MODIFIED Requirements

### Requirement: LLM extraction for unstructured formats (F3)
TXT, PDF, and email files SHALL be extracted into the `Invoice` schema by the configured LLM using structured output. Extraction SHALL behave the same with the `grok` and `claude` providers. Line items SHALL keep their raw item name, and any qualifier text (such as "rush order") SHALL go into the line-item note.

#### Scenario: Typo-laden text invoice
- **WHEN** `invoice_1002.txt` ("Vndr:", "Itms:", "Amt:") is extracted
- **THEN** the vendor is "Gadgets Co.", the invoice number is 1002, there is one line item (GadgetX, quantity 20, unit price 750.00), and the total is 15000.00

#### Scenario: Invoice inside an email
- **WHEN** `invoice_1008.txt` is extracted
- **THEN** the vendor is "NoProd Industries", there are 2 line items (SuperGizmo × 12 at 400.00, MegaSprocket × 6 at 850.00), the total is 9900.00, and the email signature and greeting are ignored

#### Scenario: Repeated item with a qualifier and a shipping line
- **WHEN** `invoice_1010.txt` is extracted
- **THEN** there are 4 line items, the last with raw name WidgetA, quantity 4, unit price 300.00, and note "rush order"; subtotal 6700.00, tax 335.00, shipping 150.00, and total 7185.00

#### Scenario: Same result across providers
- **WHEN** `invoice_1001.txt` is extracted once with `grok` and once with `claude`
- **THEN** both produce the same invoice number, vendor, line items, and totals
