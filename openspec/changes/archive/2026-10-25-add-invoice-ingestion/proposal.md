# Proposal

## Why

Acme's invoices arrive in six formats with typos, OCR noise, inconsistent dates, and invoices embedded in email bodies. Nothing downstream can run until every file becomes one validated `Invoice`: not stock checks, duplicate detection, the approval rules, or payment. This change builds that front door. Structured formats are parsed deterministically, and the LLM extracts only what plain code can't read. A file that can't be read reliably fails closed and is never guessed at.

## What Changes

- **F1 Format router (P0):** detects JSON, CSV, XML, TXT, PDF, and email-style text by file extension plus content sniffing. An unreadable or empty file produces an `EXTRACTION_FAILED` finding instead of a crash.
- **F2 Deterministic parsers (P0):** JSON, CSV, and XML parsers that make no LLM call. The CSV parser handles both layouts in the data: key/value rows with repeated keys (INV-1006, two line items) and tabular rows with a `Subtotal:`/`Tax`/`Total:` footer (INV-1007, INV-1015).
- **F3 LLM extraction (P0):** TXT, PDF (text layer via `pdfplumber`), and email-style text are extracted into the `Invoice` schema with `with_structured_output(Invoice)` through the `llm-provider` factory. It works the same with Grok, Claude, or the offline `RuleBasedLLM`. Invoice text is wrapped in delimiters and labeled as untrusted data.
- **F4 Extraction self-correction loop (P0):** if Pydantic validation fails, or line items don't sum to the subtotal within $0.01, the error text goes back into the prompt for up to 2 retries. After that the invoice fails closed with a CRITICAL `EXTRACTION_FAILED` finding. Every attempt is logged.
- **F5 SKU matching (P0):** raw item names resolve to SKUs through the `item_aliases` table first, then a `rapidfuzz` match at a score of 90 or above. "Widget A" and "Gadget X" map to their SKUs. "SuperGizmo" stays unmatched and is marked unknown for validation to flag.
- **F6 OCR, date, and money cleanup (P0):** fixes letter O read as zero ("2O26", "$3,500.O0") and parses ISO, MM/DD/YYYY, "Jan 30 2026", "January 27, 2026", and "26-Jan-2026" dates. Relative dates such as "yesterday" leave the due date empty with the source text kept in `due_date_raw`, so validation raises `INVALID_DUE_DATE`. Invoice numbers are normalized ("1002", "INV 1012" → `INV-1002`, `INV-1012`) so duplicate detection can match them.
- **F7 Currency conversion (P1):** non-USD totals convert to USD at a fixed rate from config (INV-1014, EUR). Both the original and USD amounts are stored, and an INFO `CURRENCY_CONVERTED` finding notes the conversion.

## Capabilities

### New Capabilities
- `invoice-ingestion`: turns any supported invoice file into an extracted `Invoice` plus raw text and source format. Covers format routing, deterministic parsers, LLM extraction, and the extraction self-correction loop (F1–F4).
- `invoice-normalization`: turns an extracted `Invoice` into the canonical `Invoice` that validation consumes. Covers SKU resolution, OCR/date/money/invoice-number cleanup, and currency conversion (F5–F7).

### Modified Capabilities
<!-- None: no specs exist yet. Depends on data-model, llm-provider, and audit-logging from add-project-foundation. -->

## Impact

- **Code:** `backend/src/acme/ingestion/` (router, parsers, PDF text, LLM extractor) and `backend/src/acme/normalization/` (SKU matcher, cleaners, FX). Prompt `backend/prompts/extraction.*`. Tests in `backend/tests/` per parser, normalizer, and retry path.
- **Depends on** `add-project-foundation`: the `Invoice`, `LineItem`, and `Finding` models (`data-model`), the `item_aliases` and `inventory` tables, `get_chat_model("extraction")` (`llm-provider`), and `audit_log`/`llm_calls` writes (`audit-logging`).
- **Consumed by** `add-validation-and-approval` (reads the canonical `invoice` and findings) and `add-agent-workflow` (wires the Ingestion and Normalizer nodes and the `EXTRACTION_FAILED` route to Disposition).
- **Dependencies:** `pdfplumber`, `rapidfuzz`, `python-dateutil`.
- **Config:** `FX_RATES` (default `EUR=1.08`, declared in `add-project-foundation`'s settings catalog), which is P1.
- **Golden dependency:** the golden suite (F20, `add-agent-workflow`) expects INV-1014 PAID with `CURRENCY_CONVERTED`, which needs P1 F7. Without it INV-1014 is held with `CURRENCY_UNSUPPORTED`.
