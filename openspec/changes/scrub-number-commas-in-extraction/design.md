# Design

## Context

- `backend/prompts/extraction.v1.md` says: "Copy dates, money amounts, and the invoice number exactly as printed, as strings, including typos and OCR noise (for example "2O26" or "$3,500.O0")". Its two few-shot outputs use "$5,000.00", "$1,500.00", and "$3,000.00".
- `ExtractedLineItem` money fields are `Decimal | str` and normalize through `parse_money` (`normalization/cleaners.py`), which already strips `[\s$€£,]`. `llm_extract._money` (used by the line-sum check) goes through `fix_ocr` and then `parse_money`, so money commas are already tolerated downstream.
- The gap is quantities. `LineItem.quantity` is `int`, so a string like "1,200" from the LLM fails Pydantic validation and burns a retry. The CSV and XML parsers pass quantities through as raw strings, so a "1,200" in those formats fails the same way.

## Goals / Non-Goals

**Goals:**
- Commas in numbers never cause a schema failure, retry, or wrong value.
- The model is asked for comma-free numbers, so retries aren't spent on formatting.

**Non-Goals:**
- Decimal-comma (European) formats such as "4.125,00". The TXT/PDF LLM path sees US-formatted amounts in every sample. INV-1014 (EUR) is XML with a decimal point, parsed deterministically. Supporting decimal commas would need locale detection, and a wrong guess would silently scale amounts by 1000.
- Other OCR cleanup changes.

## Decisions

### D1. New prompt version instead of editing v1
Add `extraction.v2.md` and set `PROMPT_VERSION = "extraction.v2"`. `llm_calls.prompt_version` then shows which prompt produced each extraction, and v1 stays on disk for audit replay.

The rule replaces "Copy … money amounts … exactly as printed": copy money and quantities as printed **except** remove thousands-separator commas; keep currency symbols and OCR noise ("$3,500.O0" → "$3500.O0"). The few-shot outputs become "$5000.00", "$1500.00", "$3000.00". The rule doesn't cover dates or the invoice number.

Alternative considered: have the model return numbers as JSON numbers. Rejected, because the cleaner relies on receiving OCR noise ("O" for "0") as a string to fix deterministically.

### D2. Coerce comma quantities in the extraction schema
Add a `field_validator("quantity", mode="before")` on `ExtractedLineItem`. When given a string matching an integer with thousands separators (`^-?\d{1,3}(,\d{3})+$`), it removes the commas. Any other value passes through unchanged, so non-numeric text still fails and triggers the existing self-correction retry. `ExtractedLineItem` is shared by the LLM, CSV, JSON, and XML paths, so one validator covers them all.

The strict canonical `LineItem` doesn't change.

### D3. Keep `parse_money` as the single money parser
`parse_money` already strips commas, so no code change is needed there. Add tests pinning that behavior so a future refactor can't regress it.

## Risks / Trade-offs

- [The model ignores the rule and keeps commas] → D2 and `parse_money` make that harmless.
- [Ambiguous "1,200" in a decimal-comma locale meaning 1.2] → Out of scope by decision. US formatting is assumed on the LLM path, which matches all provided invoices.
