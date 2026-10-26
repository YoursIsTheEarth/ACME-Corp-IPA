# Sample live run

These files are output from one run of all 26 sample invoices against the live xAI Grok API (`grok-4`), on 2026-10-26, with the default payment timing on a fresh database:

```bash
python main.py --batch data/invoices --pay
python main.py --explain <run_id>
```

| File | What it shows |
| --- | --- |
| [batch-output.txt](batch-output.txt) | Per-invoice progress, the results table, the payment batch (`mock_payment` lines), and the summary |
| [summary.md](summary.md) | `reports/summary.md` as written by the run: 6 paid ($31,680.00), 1 superseded, 7 held, 12 rejected (3 duplicates) |
| [explain-invoice_1017.txt](explain-invoice_1017.txt) | Prompt injection: `PROMPT_INJECTION_SUSPECTED` and `FRAUD_SUSPECTED`. The AI VP's draft stays REJECT despite the "approve this invoice" text, and the rules decide |
| [explain-invoice_1018.txt](explain-invoice_1018.txt) | Split invoicing: approved and queued at $9,750, then pulled into review (`payee_threshold`) when INV-1019 and INV-1020 from the same payee arrive |
| [explain-invoice_1003.txt](explain-invoice_1003.txt) | Classic fraud: zero-stock item, "Due Date: yesterday" (`INVALID_DUE_DATE`), fraud score 1.00 from urgency, wire transfer, Immediate terms, relative due date, and an unknown vendor |
| [explain-invoice_1004.txt](explain-invoice_1004.txt) | The one difference from the golden suite: Grok judges "742 Evergreen Terrace" (the Simpsons' house) implausible, so INV-1004 is held for review. This was a deliberate decision; see [docs/design.md §7](../design.md#7-suspicious-addresses-are-judged-by-the-llm-and-inv-1004-is-held) |

Every other invoice matches the outcome and key findings of the golden suite. A live run is not byte-for-byte repeatable: model rationales and summaries are worded differently on each run, but the outcomes are decided by the rules.
