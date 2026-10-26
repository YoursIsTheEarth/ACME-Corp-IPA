# Implementation Decisions

This document records the decisions made while building the prototype, why each was made, and where it departs from the case brief or the original spec. The feature spec is in [`Acme Invoice Agents — Design & Feature Spec.md`](../Acme%20Invoice%20Agents%20—%20Design%20&%20Feature%20Spec.md). The requirements as built are in [`openspec/specs/`](../openspec/specs), and every change that shaped them is in [`openspec/changes/archive/`](../openspec/changes/archive).

## 1. The LLM reads and reasons; code decides about money

The agents use the LLM for what it is good at:
- reading messy documents
- choosing which checks to run
- judging plausibility
- writing a VP-style rationale

Everything that decides whether money moves is deterministic Python called as a tool: stock, arithmetic, duplicates, vendor approval, price variance, the payee threshold, and the approval rules.

- **The rules engine sets the floor.** A CRITICAL finding forces REJECT, and a WARNING forces NEEDS_REVIEW.
- **The LLM can only tighten.** It may move APPROVE to NEEDS_REVIEW, never REJECT or NEEDS_REVIEW to APPROVE. This is why the prompt-injection invoice (INV-1017) cannot talk its way into an approval, even when the model is fooled.
- **Every deterministic check always runs.** The Validation agent picks which tools to call, and any check it skips is run anyway before the findings are final.

**Why:** outcomes are repeatable and testable, and an auditor can trace every rejection to a rule, not to a model's mood.

## 2. A real LLM, not a simulation

The case says to assume no internet and simulate everything locally. We kept payment and inventory local (`mock_payment`, SQLite) but run the agents on Grok (`grok-4`, the default) or Claude. Offline mode was built first and then removed: a scripted model only proves the plumbing works, not that the agents can read Acme's invoices.

- Without an API key, the CLI stops processing with a message naming the variable to set. The web app loads with a "No LLM token provided" banner.
- Tests never call a live model. They use a deterministic fake (`backend/tests/fake_llm.py`) that no setting or flag can select outside the test suite.

## 3. Fail closed, and hold rather than guess

No path produces a payment without a verified outcome:
- an extraction that fails three times
- an unreachable or blocked model
- an unparseable file
- an ambiguous case

Each of these ends REJECT (with the reason) or NEEDS_REVIEW (with what a person should check). A held invoice pauses its LangGraph run, which is checkpointed to SQLite. A named reviewer's decision resumes that same run, which can be days later.

## 4. Payment is separate from approval

Approval only queues a payment. A payment batch is the only code that calls `mock_payment`, and it is idempotent per vendor, invoice number, and revision, so nothing is paid twice. When batches run is a finance decision, made on the Admin page and audited with the name of whoever saved it:
- **Delay payments** (default on): approved invoices wait in the Payment Queue.
- **Pay at end of day** (default off): a daily batch at 5:00 PM America/Chicago when enabled.
- **Pay when the queue is empty** (default on).

A revision of an already paid invoice pays only the difference. A revision that lowers a paid total is held, so a person confirms the credit.

## 5. Untrusted invoice text and prompt injection

Document text reaches models only inside untrusted-data delimiters, with any copy of a delimiter in the text removed. A deterministic detector scans the whole document for text aimed at the agents:
- "ignore previous instructions" and "SYSTEM OVERRIDE"
- fake "Critic: pass" verdicts
- spoofed delimiters and role markers
- "approve this invoice"

A match is CRITICAL `PROMPT_INJECTION_SUSPECTED`: the invoice is rejected with the fraud flag. Urgency wording ("URGENT - pay immediately") stays an ordinary fraud signal, not an injection.

## 6. Split invoicing: the cumulative payee threshold

One payee billing just under the $10,000 VP threshold several times, or doing so through differently named vendors at one remit-to address, would pass each invoice on its own. A payee registry resolves every invoice by name, alias, or address. Then, within any rolling 30-day span, it sums **every invoice received**: rejected ones count, and each invoice number counts once at its latest revision. Over $10,000 across two or more invoices raises WARNING `PAYEE_CUMULATIVE_THRESHOLD` (review). Earlier invoices in the span are flagged too:
- queued payments are pulled back into review
- paid ones get a retroactive audit flag; money already paid is not recalled

## 7. Suspicious addresses are judged by the LLM, and INV-1004 is held

The first build flagged addresses from a hardcoded list (1600 Pennsylvania Ave, taken from INV-1005). That list catches only the addresses someone thought of in advance, so it was replaced with an LLM plausibility judgment: "is this a credible business remit-to address?" An implausible address raises WARNING `SUSPICIOUS_ADDRESS` (source `llm`), which holds the invoice for review.

**Decision: INV-1004 is held for review, against the case's expected outcome.** The case lists INV-1004 (Precision Parts Ltd.) as a normal invoice that should pass. Its vendor address is **742 Evergreen Terrace, Springfield**, the Simpsons' house. Every live Grok run flags it as implausible, so INV-1004 and its revision are held instead of paid.

We decided **not** to change the data or the check:
- A fictional TV address on a vendor invoice is exactly the kind of thing an AP clerk should question.
- The cost of the hold is one reviewer decision. The cost of the alternative (training the system to ignore an implausible address because the answer key says so) is a weaker fraud check on real data.
- The hold is visible and explained: "Why it's held" shows the model's reason, and approving it in Elevated Review pays it as normal.

The golden test suite uses the scripted fake model, which judges this address plausible, so its expected numbers (below) still show INV-1004 paid. Live runs differ from it only in this.

## 8. Rounding differences go to review, real math errors are rejected

Any arithmetic difference of a cent or more used to be a CRITICAL `MATH_MISMATCH`, so an invoice a few cents off from rounding was rejected outright. The check now uses a band, applied separately to each line, the subtotal, and the total:

| Difference | Finding | Outcome |
| --- | --- | --- |
| under $0.01 | none | — |
| $0.01 to `MATH_ROUNDING_TOLERANCE_USD` (default $1.00) | WARNING `MATH_ROUNDING` (difference and tolerance as evidence) | held for review |
| over the tolerance | CRITICAL `MATH_MISMATCH` | rejected |

Ingestion's self-correction loop, which retries when the line items don't add up, accepts the same tolerance. Otherwise a 2-cent difference would end as `EXTRACTION_FAILED` before validation could send it to review. The tolerance is a flat dollar amount, not a percentage: rounding error does not grow with invoice size, and a flat cap is easy to explain to AP staff. Every planted math error in the sample data is $50 or more, so all sample outcomes are unchanged. Setting the tolerance to 0 restores reject-on-any-cent.

## 9. Hardening found by running against the live model

The first live batch run exposed behavior the fake model never shows. Each problem below is fixed and covered by a test:

| Live behavior | Effect | Fix |
| --- | --- | --- |
| Grok returns `""` for `original_total` on USD invoices | Clean invoices (INV-1001, INV-1011.txt) failed extraction 3 times and were rejected | A blank value means "not stated"; the extraction prompt (`extraction.v3`) asks for null |
| Grok drops "Due Date: yesterday" or puts it in `due_date_raw` | INV-1003 lost `INVALID_DUE_DATE` and its relative-due-date fraud signal | The normalizer reads `due_date_raw`; a printed `Due Date:` value is copied when the model leaves it blank |
| A request timed out | Only 429 and 5xx errors were retried | Timeouts and connection failures are retried with the same backoff |
| A `.env` written before newer fraud signals existed | The prompt-injection weight counted as 0, so INV-1017 lost `FRAUD_SUSPECTED` | A `FRAUD_SIGNAL_WEIGHTS` setting is merged over the defaults |

## 10. Testing strategy

- **About 990 tests** (backend pytest, Angular component tests, Playwright end-to-end) run with no key and no network.
- **A 26-file golden suite** pins the outcome, key findings, and payment totals for every sample invoice, in both the delayed and the immediate payment configuration. It runs on scripted extractions, so it tests the pipeline's logic, not the model's reading.
- **Live runs** check the model's reading. A recorded live run is in [`docs/sample-run/`](sample-run).

| Run | Paid | Held | Rejected | Superseded | Paid total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Golden suite (fake model, default timing) | 7 | 6 | 12 | 1 | $37,620.00 |
| Live Grok run (default timing) | 6 | 7 | 12 | 1 | $31,680.00 |

The only difference is INV-1004 (section 7): live, both versions are held, so the revision's $5,940.00 is not paid.

## 11. Scope cuts

Each cut was made to ship a working end-to-end prototype. Each is listed with what a production version needs.

- **Stock is checked per invoice, not across invoices.** Validation compares each invoice's quantities with the stock on hand. It does not reserve or decrement stock when an invoice is approved or paid, and it does not total quantities across open invoices. We cut this to keep the sample invoices independent of each other, so each can be tested on its own regardless of processing order. As a result, the six invoices paid in the sample run together bill 47 WidgetA against 15 in stock, 29 WidgetB against 10, and 6 GadgetX against 5, and each one passes on its own. **For a real product this is a core requirement:** the system must track quantities already invoiced (approved, queued, or paid) against inventory, so Acme is never charged for more goods than it holds or received. The natural design is a running "invoiced quantity" per SKU, updated at disposition, with `STOCK_EXCEEDED` checked against stock minus what is already committed.
- **No OCR.** An image-only PDF fails closed as `EXTRACTION_FAILED`. All the provided PDFs carry a text layer.
- **No real email intake, bank API, or cloud deployment,** as the case allows. Emails are processed as `.eml` files.
- **No login.** Reviewer and releaser names are typed by hand and recorded in the audit log.
- **Fixed currency rates.** Non-USD amounts convert at configured rates, not live FX. An unsupported currency is held for review.
