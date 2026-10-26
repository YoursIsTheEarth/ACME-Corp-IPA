# Acme Invoice Agents — Design & Feature Spec

Oct 24, 2026 · @Luc

## Overview

We will build a local multi-agent system, powered by Grok or Claude, that takes any Acme invoice file and ends in exactly one outcome: **paid**, **rejected with reasons**, or **held for human review**. Approved invoices are paid in batches: at the end of the day, when the Invoice Queue goes idle, or when a person clicks Pay. Every decision is traceable to a finding, a rule, or an LLM rationale stored in an audit ledger.

**Problem.** Acme loses about $2M a year on manual invoice processing: a 30% error rate, 5-day delays, and VP approvals buried in email chains.

**Design principle.** The LLM reads and reasons; deterministic code decides about money. The LLM extracts data from messy documents, normalizes it, and writes the approval rationale. Stock checks, arithmetic, duplicate detection, and hard approval rules are plain Python that agents call as tools, so outcomes are testable and repeatable.

**Goals**

- Process all 20 provided invoice files (16 invoice numbers) end to end from one CLI command, with the expected outcome on each.
- Catch every planted issue: stock overruns, unknown and zero-stock items, bad data, fraud signals, duplicates, revisions.
- Show agentic behavior the case asks for: tool calling, structured outputs, and two self-correction loops.
- Give a reviewer a clear view of what happened and why, in the terminal and in the ACME Corp IPA web app, where people upload invoices and decide held ones.

**Non-goals**

- Real email intake, real banking, authentication, or cloud deployment.
- OCR of image-only scans (the provided PDFs carry a text layer).
- Learning from past decisions or a vendor master beyond a seeded table.

**Success metrics for the prototype**

| Metric | Target |
| --- | --- |
| Golden outcomes matched | 20 of 20 files |
| Bad payments released | 0 |
| Duplicate payments | 0 |
| Time per invoice (Grok or Claude) | Under 30 seconds |
| Runs with no API key | Yes, in offline mode |

## Agent workflow

&#91;embedded content: agent workflow · 6 agents, 3 loops, 3 outcomes\]

Each invoice flows top to bottom through one LangGraph `StateGraph`, with three loops: Ingestion retries its own extraction, Validation calls tools until the LLM is done, and Approval revises with the Critic. LLM-powered agents can explain and tighten decisions, but the rules engine sets the floor, and only the Pay node moves money.

## Agent roles and handoffs

Six agents share one `InvoiceState` object passed along a LangGraph `StateGraph`. Each agent reads the fields it needs, writes its own fields, and appends to `state.trace` so the audit ledger can replay the run.

| Agent | Reads | Writes | Tools it calls | Uses the LLM for | Loop |
| --- | --- | --- | --- | --- | --- |
| 1. Ingestion | file path | `raw_text`, `source_format`, `extracted` | `detect_format`, `parse_json`, `parse_csv`, `parse_xml`, `pdf_to_text` | Extracting fields from TXT, PDF, and email text into the `Invoice` schema | Extract, then self-correct (max 2 retries) |
| 2. Normalizer | `extracted` | `invoice` (canonical) | `match_sku` (fuzzy), `parse_date`, `fix_ocr`, `convert_currency` | Only when a SKU or date can't be resolved deterministically | None |
| 3. Validation | `invoice` | `findings[]` | `lookup_item`, `check_stock`, `reconcile_math`, `check_duplicate`, `check_vendor`, `fraud_signals` | Choosing which tools to call and summarizing findings | Tool-call loop until it declares done |
| 4. Approval (VP) | `invoice`, `findings` | `decision_draft` | `apply_policy` (rules engine) | Writing the decision and rationale as a VP would | Receives critiques from the Critic |
| 5. Critic | `decision_draft`, `findings`, policy | `critique` | `apply_policy` | Checking the draft against rules and evidence | Approval revises until Critic passes (max 2 rounds) |
| 6. Disposition | final `decision` | `payment_queue_entry` or `rejection` | `queue_payment`, `supersede_original`, `record_rejection`, `enqueue_review` | Nothing; deterministic | None |

**Handoff rules**

1. Ingestion hands off only when the extracted data passes the Pydantic schema and the math check, or after 2 failed retries. On failure it routes straight to Disposition with an `EXTRACTION_FAILED` finding.
2. Validation always runs every deterministic check, even if the LLM skips a tool call. The LLM adds the narrative and any judgment-based signals on top.
3. The rules engine runs before the LLM in Approval. A critical finding forces REJECT, and the LLM can only explain it, never override it.
4. The LLM may tighten an outcome (APPROVE to REVIEW) but never loosen one (REJECT to APPROVE).
5. Only the Payment Executor moves money, outside the graph and in batches. The graph's last node queues approved payments; the executor checks an idempotency key (`vendor + invoice_number + revision`) before calling `mock_payment`.

**Approval policy (rules engine)**

| Condition | Outcome |
| --- | --- |
| Any CRITICAL finding (unknown item, stock exceeded, negative qty, math mismatch, missing vendor, duplicate) | REJECT |
| Fraud score at or above threshold | REJECT + fraud flag |
| Any WARNING finding (price variance over 10%, due date before invoice date) | NEEDS REVIEW |
| Total over $10,000 with no findings | VP scrutiny: LLM review + Critic, then APPROVE or NEEDS REVIEW |
| Total $10,000 or less with no findings | AUTO-APPROVE (the LLM still writes a one-line rationale) |
| Revision of an invoice not yet paid | Replaces the original (marked Superseded, its queued payment cancelled); the revision is judged by the rows above as a new invoice for its full total |
| Revision of a paid invoice with a higher total | Judged as a whole by the rows above; if approved, only the delta is queued |
| Revision of a paid invoice with a lower total | NEEDS REVIEW: a person confirms with the vendor that a credit or refund will be provided |

APPROVE never pays directly. It adds the invoice to the payment queue, and the Payment Executor pays it in the next batch.

## Payment batches

Approved invoices are not paid the moment they are approved. The workflow ends by adding them to a payment queue, and a separate Payment Executor pays that queue in batches. Holding payments until a batch runs gives a late revision the chance to replace an invoice before money moves, and gives finance one predictable payment run a day.

**When a batch runs**

| Trigger | When | What it pays |
| --- | --- | --- |
| End of day | Daily at `PAYMENT_BATCH_TIME` (default 5:00 PM, America/Chicago) | Everything queued |
| Invoice Queue idle | No invoice has been in Uploaded, Extracting, Validating, or Deciding for `PAYMENT_IDLE_DELAY_S` (default 60 seconds), and the payment queue is not empty | Everything queued |
| Pay all | A person clicks Pay all on the Payment Queue page | Everything queued |
| Pay selected or Pay now | A person checks rows, or clicks one row's button | Only those rows |

Invoices in Awaiting review don't block the idle trigger, because they can wait for days. The delay keeps a batch from firing between files of a multi-file upload. `PAYMENT_AUTO_IDLE=false` turns the idle trigger off.

**Executor rules**

1. One batch runs at a time, under a lock. Rows being paid show Paying and can't be picked again.
2. Before paying, each row is re-checked: still queued, not superseded, and its idempotency key (`vendor + invoice_number + revision`) not already used. Then the executor calls `mock_payment(vendor, amount)`.
3. A failed call marks the row Failed with the error. The next batch retries it, up to 3 attempts; after that it moves to Elevated Review.
4. Each batch writes a `payment_batches` record: trigger, who started it, row count, total, and per-row results.

**Revisions and the queue**

| Original invoice when the revision arrives | What happens |
| --- | --- |
| Not yet paid (queued, held for review, or rejected) | The revision replaces the original. The original is marked Superseded and any queued payment for it is cancelled. The revision is judged as a new invoice and, if approved, queued for its full total. |
| Paid, and the revision's total is higher | The revision is judged as a whole under every normal rule. If approved, only the delta is queued. |
| Paid, and the revision's total is lower | Held in Elevated Review. A reviewer confirms with the vendor that a credit or refund will be provided and records it in the rationale. Nothing is paid. |
| Paid, same total | Recorded as Revised, no payment due. |
| Being paid at that moment | Treated as paid once the payment completes, then handled by the rows above. |

From the CLI, `--pay` runs a batch after processing, and `python main.py payments run` runs one on demand.

## Web app: ACME Corp IPA

ACME Corp IPA is an Angular web app over a FastAPI backend that runs the same agent pipeline as the CLI. People drop invoice files on the Home page, watch them move through the Invoice Queue, decide held invoices in Invoice Elevated Review, release approved payments from the Payment Queue, and check results in the Resolution Audit and Payments.

| Layer | Choice | Why |
| --- | --- | --- |
| Frontend | Angular 18 with standalone components, Angular Material, and RxJS | Your requested stack; Material gives the sidebar, tables, dialogs, and toasts out of the box |
| Backend | FastAPI with Uvicorn | Python, so it calls the LangGraph pipeline directly; built-in request validation and OpenAPI docs |
| Live updates | Server-Sent Events, with polling as the fallback | One-way status pushes are all the pages need; simpler than WebSockets |
| Workflow pause | LangGraph `interrupt()` with a SQLite checkpointer | A held invoice waits for a person, then resumes where it stopped |
| Storage | The existing SQLite file plus an `uploads/` folder | Runs locally with no services to install |
| Payment scheduling | APScheduler inside the FastAPI process | Runs the end-of-day batch and the idle check with no extra services |

&#91;embedded content: invoice status by page · 4 stages, review hold, payment queue, 3 end states\]

Each status appears on exactly one page, except Awaiting review, which shows in both the Queue and Elevated Review so nothing waiting is hidden. Approved invoices wait in the Payment Queue until a batch pays them, and Payments is the paid subset of the Audit.

## Web app pages

ACME Corp IPA has five pages behind one persistent left sidebar. All four tables share the same Angular Material table setup: sortable columns, a search box, pagination, a status chip with consistent colors, and a row click that opens the invoice detail drawer.

**App shell and sidebar**

- Top of the sidebar: the "ACME Corp IPA" name and a short tagline, "Invoice Processing Automation."
- Menu items in order: Home, Invoice Queue, Invoice Resolution Audit, Invoice Elevated Review, Payment Queue, Payments. The active page is highlighted.
- Invoice Queue, Invoice Elevated Review, and Payment Queue show a live count badge, so reviewers see waiting work from any page.
- Below 960 px wide, the sidebar collapses to icons and opens as an overlay.

**Home**

| Element | Behavior |
| --- | --- |
| Header | "Welcome to ACME Corp IPA" with one line on what the system does |
| Drop zone | Drag and drop one or many files; the zone highlights while files hover over it |
| Browse button | Opens the computer's file picker with multi-select, limited to .pdf, .txt, .csv, .json, .xml, .eml |
| Upload list | One row per file: name, size, upload progress, then "Queued" or an inline error (wrong type, over 10 MB, empty file) |
| After upload | A "View in Invoice Queue" link; a toast confirms how many files were accepted |
| Summary tiles (P1) | In queue, awaiting review, paid today, rejected today |

**Invoice Queue:** every uploaded invoice that is not yet resolved, with live stage updates.

| Column | Content |
| --- | --- |
| File | Original file name and format icon |
| Invoice # / Vendor | Filled in once extraction finishes; "Extracting..." before that |
| Amount (USD) | Total after currency conversion |
| Stage | A 5-step progress strip: Uploaded, Extracting, Validating, Deciding, Awaiting review |
| Status | Processing, Retrying extraction, or Awaiting review |
| Uploaded / Time in stage | Timestamp and elapsed time |

An approved invoice leaves this table for the Payment Queue; a rejected one moves to the Resolution Audit.

**Invoice Resolution Audit:** every invoice that finished the process, with the reasoning behind each decision.

| Column | Content |
| --- | --- |
| Invoice # / Vendor / Amount (USD) | From the extracted invoice |
| Final status | Paid, Rejected, Duplicate, Superseded, or Credit confirmed |
| Decided by | Auto (rules), AI VP (with provider and model), or the reviewer's name |
| Key findings | Up to 3 finding chips, such as Stock exceeded or Price variance |
| Completed | Timestamp and total processing time |

Expanding a row shows a timeline of rationale, one entry per stage: extraction notes and retries, validation findings with evidence, the rules that fired, each AI VP draft with the Critic's response, the reviewer's rationale if there was one, and the payment or rejection record. Filters by status and date; export to CSV.

**Invoice Elevated Review:** invoices the system held for a person to decide.

| Column | Content |
| --- | --- |
| Invoice # / Vendor / Amount (USD) | From the extracted invoice |
| Why it's held | The warning findings, such as Price variance 20%, or a revision that lowers a paid total |
| AI recommendation | The AI VP's suggested outcome and a one-line rationale |
| Waiting since | Time held |
| Actions | Approve and Reject buttons, plus View details |

Clicking Approve or Reject opens a dialog:

- It shows the invoice summary, the findings, and the AI recommendation.
- Fields: reviewer name, typed by hand (required, 1 to 50 characters after trimming spaces, with a counter showing characters left; no login; remembered in the browser for next time) and rationale (required, at least 15 characters).
- Confirming sends the decision to the backend, which resumes the paused workflow. Approve adds the invoice to the Payment Queue; Reject sends it to the rejection log.
- The row leaves the table, the badge count drops, and a toast confirms the result. If someone else already decided the invoice, the dialog says so and refreshes.

**Credit or refund holds.** When a paid invoice is revised to a lower total, the row shows the amount overpaid, and the buttons read Credit confirmed and Reject revision. The rationale must record what the vendor agreed to: a credit note or a refund, and the amount. Nothing is paid either way.

**Payment Queue:** approved invoices waiting to be paid, and the controls to pay them.

- A header shows the count and total queued, the next scheduled batch ("Today 5:00 PM CT"), and whether auto-pay on idle is on.
- Pay all pays every queued row; Pay selected pays the checked rows; each row has its own Pay now button.
- Every pay action opens a confirm dialog with the row count, the total, and the same typed name field as reviews (1 to 50 characters), so the payment record shows who released it.

| Column | Content |
| --- | --- |
| Select | Checkbox for Pay selected |
| Invoice # / Vendor | Linked to the invoice detail drawer |
| Amount (USD) | What this payment will send |
| Type | Full invoice, Revision replacing original, or Revision delta |
| Approved by | Auto, AI VP, or the reviewer's name |
| Queued at | Timestamp |
| Status | Queued, Paying, or Failed (with the error; retried next batch) |
| Action | Pay now |

When a revision replaces a queued invoice, the original's row disappears (it shows as Superseded in the Audit), the revision's row appears with its full total, and a toast explains the swap. While a batch runs, its rows show Paying and the buttons are disabled. When it ends, paid rows move to Payments and a toast sums up the batch, for example "Batch B-0142: 7 paid, $38,290, 0 failed."

**Payments:** every invoice that was paid.

| Column | Content |
| --- | --- |
| Payment ID | From the mock payment ledger |
| Invoice # / Vendor | Linked to the invoice's audit entry |
| Amount paid (USD) | Plus the original amount and currency when it was not USD. A revision payment shows "Delta for R1" and the revised total |
| Approved by | Auto, AI VP, or the reviewer's name |
| Paid at | Timestamp |
| Idempotency key | Shows why a duplicate was never paid twice |
| Batch | Batch ID and what started it: End of day, Invoice Queue idle, Pay all, Pay selected, or Pay now |
| Released by | System for scheduled and idle batches, or the name typed by the person who clicked Pay |

A footer shows the total paid for the current filter. Filters by date and vendor; export to CSV.

**Invoice detail drawer (shared):** opens from any table. It shows a preview of the original file beside the extracted fields, the findings, and the full stage timeline from the audit ledger.

## Backend API

A FastAPI service wraps the same pipeline the CLI uses, so both paths produce identical results. Uploads return right away; a background worker runs each invoice through the LangGraph graph and pushes status changes to the browser.

| Method | Path | Used by | Purpose |
| --- | --- | --- | --- |
| POST | `/api/invoices` | Home | Multipart upload of one or many files. Validates type and size, stores each file, and returns 202 with `id`, `file_name`, and `status` per file |
| GET | `/api/invoices?view=queue` | Invoice Queue | Unresolved invoices with current stage |
| GET | `/api/invoices?view=audit` | Resolution Audit | Resolved invoices with final status and key findings; filters for status, date, and search text |
| GET | `/api/invoices?view=review` | Elevated Review | Invoices paused for a human, with findings and the AI recommendation |
| GET | `/api/invoices/{id}` | Detail drawer, audit row | Full record: extracted fields, findings, decisions, and the stage timeline |
| GET | `/api/invoices/{id}/file` | Detail drawer | The original file for preview or download |
| POST | `/api/invoices/{id}/review` | Review dialog | Body: `decision` (approve or reject), `rationale`, `reviewer`. The reviewer name must be 1 to 50 characters after trimming, or the API returns 422. Resumes the workflow. Returns 409 if the invoice is no longer awaiting review |
| GET | `/api/payments` | Payments | Paid invoices with payment ID, amount, approver, and idempotency key |
| GET | `/api/stats` | Home tiles, sidebar badges | Counts by status and today's totals |
| GET | `/api/events` | All pages | Server-Sent Events stream: `invoice.created`, `invoice.stage_changed`, `invoice.resolved`, `payment.queued`, `payment.cancelled`, `batch.started`, `batch.finished`, `payment.created` |
| GET | `/api/invoices.csv`, `/api/payments.csv` | Audit, Payments | CSV export of the current filter |
| GET | /api/payment-queue | Payment Queue | Queued and failed payments, the queued total, the next scheduled batch time, and whether auto-pay on idle is on |
| POST | /api/payment-queue/execute | Pay all, Pay selected, Pay now | Body: optional ids (omit for all) and released\_by (1 to 50 characters). Starts a batch and returns 202 with the batch ID; returns 409 if a batch is already running |
| GET | /api/payment-batches | Payments, toasts | Batch history: trigger, released by, count, total, failures |

**Human-in-the-loop.** When the rules engine or the LLM returns NEEDS\_REVIEW, the graph pauses with LangGraph's `interrupt()`, and its state is saved by a SQLite checkpointer. The review endpoint resumes that exact run with the reviewer's decision, so the approval, payment, and audit trail stay in one continuous workflow.

**New tables** (added to `acme.db`)

| Table | Columns |
| --- | --- |
| `invoice_runs` | `id`, `file_name`, `stored_path`, `uploaded_at`, `status`, `stage`, `invoice_number`, `vendor`, `total_usd`, `final_status`, `decided_by`, `completed_at` |
| `review_decisions` | `run_id`, `reviewer`, `decision`, `rationale`, `decided_at` |
| payment\_queue | id, run\_id, invoice\_number, revision, vendor, amount\_usd, kind (full, replacement, delta), status (queued, paying, paid, failed, cancelled), attempts, last\_error, queued\_at, batch\_id |
| payment\_batches | batch\_id, trigger (end\_of\_day, idle, pay\_all, pay\_selected, pay\_now), released\_by, started\_at, finished\_at, count, total\_usd, failed\_count |

CORS is open only to the Angular dev server, uploads are capped at 10 MB per file, and there is no login, consistent with the prototype's non-goals.

## LLM integration: Grok or Claude

One setting, `LLM_PROVIDER`, chooses Grok or Claude for every agent. The graph, prompts, tools, rules, and tests stay the same, so switching providers is a config change, not a code change.

**How the switch works.** Agents never import an SDK. They ask a factory, `get_chat_model(role)` in `src/acme/llm/factory.py`, for a LangChain chat model:

| Provider | Package | Class | Key |
| --- | --- | --- | --- |
| Grok (default) | `langchain-xai` ([docs](https://docs.langchain.com/oss/python/integrations/chat/xai.md)) | `ChatXAI` | `XAI_API_KEY` |
| Claude | `langchain-anthropic` | `ChatAnthropic` | `ANTHROPIC_API_KEY` |
| Offline | built in | `RuleBasedLLM` | none |

Both real providers support LangChain's `bind_tools` and `with_structured_output`, which are the only two capabilities the agents rely on. The factory wraps each model with the same timeout, retry, and logging settings.

**Configuration** (`.env`, loaded with `pydantic-settings`)

| Setting | Default | Notes |
| --- | --- | --- |
| `LLM_PROVIDER` | `grok` | `grok`, `claude`, or `offline`. The CLI's `--provider` flag overrides it for one run |
| `GROK_MODEL` | a current Grok 4 model | The case README shows `grok-3`; confirm the current name in the xAI console before submitting |
| `CLAUDE_MODEL` | `claude-sonnet-5-5` | `claude-opus-5-5` for the hardest reasoning; confirm current names on Anthropic's models page before submitting |
| `LLM_PROVIDER_EXTRACTION`, `_VALIDATION`, `_APPROVAL`, `_CRITIC` | unset | Optional per-agent override, so one provider can check the other (see below) |
| `LLM_TEMPERATURE` | 0 | Extraction and decisions should be repeatable |
| `LLM_TIMEOUT_S` / `LLM_MAX_RETRIES` | 30 / 3 | Exponential backoff on 429 and 5xx |

At startup the app checks that the selected provider's key is set and stops with a clear message if not. The web app's sidebar footer shows the active provider and model.

**Cross-model critique (P1).** With per-agent overrides, Grok can draft the VP decision while Claude acts as the Critic, or the reverse. A second model catches mistakes the first one makes confidently, and the audit trail records which model said what.

**How each agent uses the LLM**

- **Structured output:** `with_structured_output(Invoice)` for extraction, `Decision` for approval, `Critique` for the critic. Pydantic validation errors are fed back into the next prompt as the self-correction signal.
- **Tool calling:** the Validation agent gets `bind_tools([...])` with the validation tools. A LangGraph `ToolNode` executes calls and loops back until the model returns no more tool calls.
- **Prompts:** one provider-neutral set, versioned in `prompts/`, each with a system role, the schema, and 1 to 2 few-shot examples from the clean invoices.
- **Guardrails:** invoice text is wrapped in delimiters and labeled as untrusted data, so lines like "URGENT - pay immediately" in INV-1003 are treated as evidence, not instructions.

**Offline mode.** The README says to assume no internet, so `LLM_PROVIDER=offline` swaps in a `RuleBasedLLM` with the same interface: regex extraction for text invoices, template rationales, and a fixed tool plan. Tests run in this mode by default, and a fixture mode replays saved Grok and Claude responses so both paths are tested without a network.

**Observability.** Every LLM call logs provider, model, prompt version, token counts, latency, and retry count to the `llm_calls` table, keyed to the invoice run. Each decision in the Resolution Audit shows which provider and model made it.

## Data model and database

All agents exchange Pydantic models, and all persistent state lives in one SQLite file, `acme.db`, created by `python -m acme.db seed`.

**Core models** (`src/acme/models.py`)

| Model | Key fields |
| --- | --- |
| `LineItem` | `sku`, `raw_name`, `quantity`, `unit_price`, `amount`, `note` |
| `Invoice` | `invoice_number`, `revision`, `vendor_name`, `vendor_address`, `invoice_date`, `due_date`, `currency`, `line_items`, `subtotal`, `tax`, `shipping`, `total`, `payment_terms`, `notes`, `extraction_confidence` |
| `Finding` | `code` (enum), `severity` (CRITICAL, WARNING, INFO), `message`, `evidence`, `source` (rule or llm) |
| `Decision` | `outcome` (APPROVE, REJECT, NEEDS\_REVIEW), `rationale`, `rules_applied`, `confidence` |
| `Critique` | `passes`, `issues[]`, `suggested_outcome` |
| `InvoiceState` | `run_id`, `file_path`, `raw_text`, `extracted`, `invoice`, `findings`, `decision_draft`, `critique`, `decision`, `payment_result`, `trace[]`, `retries` |

**SQLite tables**

| Table | Purpose | Columns |
| --- | --- | --- |
| `inventory` | Seed from the README, extended | `item` PK, `stock`, `unit_price`, `category` |
| `item_aliases` | Map OCR and spacing variants to SKUs | `alias`, `sku` ("Widget A" maps to WidgetA) |
| `vendors` | Known-vendor list for vendor checks | `name`, `aliases`, `status` (approved or unknown) |
| `processed_invoices` | Duplicate and revision detection | `vendor`, `invoice_number`, `revision`, `content_hash`, `outcome`, `run_id` |
| `payments` | Mock payment ledger | `idempotency_key` unique, `vendor`, `amount_usd`, `paid_at` |
| `audit_log` | Every agent step | `run_id`, `ts`, `agent`, `event`, `payload_json` |
| `llm_calls` | LLM observability (provider and model per call) | `run_id`, `agent`, `model`, `prompt_version`, `tokens_in`, `tokens_out`, `latency_ms` |

**Seed data**

| Item | Stock | Reference unit price (USD) |
| --- | --- | --- |
| WidgetA | 15 | 250.00 |
| WidgetB | 10 | 500.00 |
| GadgetX | 5 | 750.00 |
| FakeItem | 0 | none |

The stock values match the case README exactly. The reference prices are an assumption inferred from the clean invoices, added so price variance can be checked.

## Feature spec

The MVP is the 29 P0 features: they take all 20 files to the right outcome from either the CLI or the ACME Corp IPA web app, including the human review step. P1 features add fraud scoring, currency, price checks, live updates, cross-model critique, and tests that make the submission stand out; P2 is polish if time remains.

| ID | Feature | Priority | Acceptance criteria |
| --- | --- | --- | --- |
| **Ingestion** |  |  |  |
| F1 | Format router | P0 - MVP | Detects JSON, CSV, XML, TXT, PDF, and email-style text by extension and content sniffing. An unreadable file yields an `EXTRACTION_FAILED` finding, not a crash. |
| F2 | Deterministic parsers (JSON, CSV, XML) | P0 - MVP | Handles both CSV layouts: key/value with repeated keys (INV-1006 yields 2 line items) and tabular with a totals footer (INV-1007, INV-1015). No LLM call for these formats. |
| F3 | LLM extraction for TXT, PDF, email | P0 - MVP | `pdfplumber` text feeds LLM structured output into `Invoice`. INV-1002, 1003, 1008, 1010, and 1012 extract vendor, number, dates, line items, and totals correctly with either Grok or Claude. |
| F4 | Extraction self-correction loop | P0 - MVP | If the schema fails or line items don't sum to the subtotal within $0.01, the LLM retries with the error text (max 2). After that the invoice fails closed with a CRITICAL finding. Retries are logged. |
| **Normalization** |  |  |  |
| F5 | SKU matching | P0 - MVP | Alias table first, then fuzzy match (`rapidfuzz`, score 90 or above). "Widget A" and "Gadget X" map to SKUs; "SuperGizmo" stays unmatched and is marked unknown. |
| F6 | OCR, date, and money cleanup | P0 - MVP | Fixes letter O read as zero ("2O26", "$3,500.O0"). Parses ISO, MM/DD/YYYY, "Jan 30 2026", and "26-Jan-2026". Relative dates like "yesterday" become `INVALID_DUE_DATE`. |
| F7 | Currency conversion | P1 - Should | Non-USD totals convert at a fixed rate from config (INV-1014, EUR). Original and USD amounts are both stored; an INFO finding notes the conversion. |
| **Validation** |  |  |  |
| F8 | Inventory checks | P0 - MVP | Flags unknown items, zero-stock items, and quantity over stock, aggregated per SKU across lines. INV-1013 is flagged for 22 WidgetA against 15 in stock. |
| F9 | Data integrity checks | P0 - MVP | Flags missing vendor, missing or invalid due date, quantity of zero or less, and any mismatch between line sum, subtotal, tax, shipping, and total. INV-1009 raises at least 3 CRITICAL findings. |
| F10 | Duplicate and revision handling | P0 - MVP | Same vendor, number, and total as a processed invoice is a CRITICAL `DUPLICATE`; the second copy of INV-1011 is never paid. A new revision is an INFO `REVISION` linked to the original. Unpaid original: the revision replaces it at its full total (INV-1004 is Superseded and R1 queues $5,940). Paid original: a higher total queues only the delta; a lower total goes to Elevated Review to confirm a credit or refund. |
| F11 | Fraud signal scoring | P1 - Should | Weighted score from urgency language, wire-transfer requests, "Immediate" terms, past-due dates, unknown vendor, suspicious address, and totals just under $10,000. INV-1003 scores over the threshold; clean invoices score under it. |
| F12 | Price variance check | P1 - Should | Unit price more than 10% from the reference price is a WARNING. The INV-1010 rush line at $300 against $250 is flagged. |
| F13 | LLM validation agent with tools | P0 - MVP | The LLM receives the invoice and the tool list, decides which tools to call, and returns a findings summary. Every deterministic check still runs if the LLM omits a call. |
| **Approval** |  |  |  |
| F14 | Rules engine | P0 - MVP | Implements the approval policy table as pure functions with unit tests. Returns the floor outcome and the rules that fired. |
| F15 | AI VP review with critic loop | P0 - MVP | The LLM drafts a `Decision`; the Critic checks it against the rules and evidence; Approval revises up to 2 rounds. The LLM can tighten but never loosen the rules-engine outcome. Each round is stored in the trace. |
| **Payment and disposition** |  |  |  |
| F16 | Payment queue and batch executor | P0 - MVP | APPROVE adds a row to the payment queue; nothing is paid at approval. The executor pays queued rows with the README's `mock_payment(vendor, amount)`, one batch at a time. A repeated idempotency key pays nothing; failed rows retry up to 3 times, then go to Elevated Review. |
| F17 | Rejection log and review hold | P0 - MVP | REJECT writes reasons and findings to the log. NEEDS\_REVIEW pauses the workflow until a person decides on the Elevated Review page (or with a CLI command). |
| F38 | Batch triggers | P0 - MVP | A batch runs daily at `PAYMENT_BATCH_TIME` (default 5:00 PM Central), after the Invoice Queue has had nothing in processing for `PAYMENT_IDLE_DELAY_S` (default 60 seconds), or on Pay all, Pay selected, or Pay now. Invoices awaiting review don't block the idle trigger. Each batch is recorded with its trigger and who released it. |
| F39 | Revision replaces queued payment | P0 - MVP | When a revision of a queued invoice is approved, the original's queued payment is cancelled before any batch can pay it, and the revision is queued for its full total. If the revision is rejected or held, the original stays Superseded and unpaid. |
| **Platform** |  |  |  |
| F18 | CLI | P0 - MVP | `python main.py --invoice_path=<file>` per the README, plus `--batch <dir>`, `--provider` (grok, claude, or offline), `--pay` to run a payment batch after processing, and `--json`. `python main.py payments run` runs a batch on demand. Uses `rich` to show stage progress, findings, and the final outcome. |
| F19 | Structured logs and audit ledger | P0 - MVP | JSON logs with `run_id` and agent name. `python main.py --explain <run_id>` replays a run's trace from `audit_log`. |
| F20 | Golden test suite | P0 - MVP | `pytest` runs all 20 files in offline mode, then one payment batch, and asserts the outcome, key finding codes, and amounts paid from the test plan. Unit tests cover parsers, rules, normalizers, and the revision cases. |
| **Web app: ACME Corp IPA** |  |  |  |
| F21 | App shell and sidebar | P0 - MVP | Angular app titled ACME Corp IPA with a persistent sidebar: Home, Invoice Queue, Invoice Resolution Audit, Invoice Elevated Review, Payment Queue, Payments. Active page highlighted; Invoice Queue, Elevated Review, and Payment Queue show count badges; collapses below 960 px. The footer shows the active LLM provider and model. |
| F22 | Home page with drop zone | P0 - MVP | Generic welcome header. Dropping one or many files, or picking them with Browse, uploads them all; each file shows progress, then Queued or a clear error. Unsupported types and files over 10 MB are refused before upload. |
| F23 | Invoice Queue page | P0 - MVP | Lists every invoice still being processed or awaiting review, with its stage strip and status. Stages update without a page reload; approved invoices move to the Payment Queue and rejected ones to the Audit. |
| F24 | Invoice Resolution Audit page | P0 - MVP | Lists every resolved invoice (Paid, Rejected, Duplicate, Superseded, Credit confirmed) with decided by and key findings. Expanding a row shows the rationale timeline for every stage, including AI VP drafts, Critic responses, the provider and model behind each, and reviewer notes. |
| F25 | Invoice Elevated Review page and dialog | P0 - MVP | Lists invoices awaiting a person, with why each is held and the AI recommendation. Approve or Reject opens a dialog that requires a typed reviewer name of 1 to 50 characters and a rationale of at least 15 characters. Approve adds the invoice to the Payment Queue. Credit holds use Credit confirmed and Reject revision, and the rationale records the vendor's credit or refund. A stale decision gets a 409 message. |
| F40 | Payment Queue page | P0 - MVP | Lists queued and failed payments with type (full, replacement, delta), amount, approver, and status, plus the queued total and next batch time. Pay all, Pay selected, and per-row Pay now open a confirm dialog with a typed name of 1 to 50 characters. Rows show Paying during a batch, buttons are disabled, and a toast sums up each batch. |
| F26 | Payments page | P0 - MVP | Lists every paid invoice with payment ID, amount in USD (and original currency), approver, batch ID and trigger, released by, time, and idempotency key, with a total for the current filter. |
| F27 | REST API and upload worker | P0 - MVP | FastAPI endpoints in the Backend API section. Uploads return 202 within 1 second; a background worker runs each invoice through the same graph as the CLI. |
| F28 | Human-in-the-loop resume | P0 - MVP | NEEDS\_REVIEW pauses the LangGraph run with `interrupt()` and a SQLite checkpointer; the review endpoint resumes that run. Restarting the server does not lose held invoices or queued payments. |
| F29 | Live updates | P1 - Should | Server-Sent Events push stage changes, queue changes, and batch results to every open page. Until this lands, the tables poll every 3 seconds. |
| F30 | Invoice detail drawer | P1 - Should | Opens from any table row: original file preview beside extracted fields, findings, and the full stage timeline. |
| F31 | Batch summary and home tiles | P1 - Should | Counts per outcome, dollars queued, dollars paid, dollars blocked, and duplicates caught, shown as Home tiles and written to `reports/summary.md` after a CLI batch. |
| F32 | Frontend tests | P1 - Should | Component tests for the drop zone, the review dialog, and the pay dialog, plus one Playwright run: upload 3 files, review one, click Pay all, see them in Payments. |
| F33 | One-command setup | P1 - Should | `make setup && make dev` installs both apps, seeds the DB, and starts FastAPI and the Angular dev server together. Optional `docker compose up`. |
| F34 | Recorded LLM fixtures | P2 - Stretch | Saved Grok and Claude responses replay in tests so the golden suite exercises both LLM paths with no network. |
| F35 | CSV export | P2 - Stretch | Audit and Payments export the current filter to CSV. |
| **LLM provider** |  |  |  |
| F36 | Switchable LLM provider | P0 - MVP | `LLM_PROVIDER=grok`, `claude`, or `offline` selects the model for every agent through one factory; no agent code changes. A missing key for the chosen provider stops startup with a clear message. The golden outcomes match with either provider. |
| F37 | Cross-model critique | P1 - Should | Per-agent overrides let one provider draft the VP decision and the other act as Critic. The audit trail shows which provider and model produced each step. |

## Test plan

In a batch run of all 20 files (16 invoice numbers) followed by one payment batch, 7 are paid, 1 is superseded by its revision, 1 is held for review, and 11 are rejected, 3 of them as duplicates. Files are processed in sorted filename order, and no payment runs until the last file finishes and the idle delay passes, so INV-1004 is still queued when R1 arrives and R1 replaces it. These rows become the parametrized golden test in `tests/test_golden.py`.

| File | What it tests | Expected outcome | Paid in batch | Key finding codes |
| --- | --- | --- | --- | --- |
| invoice\_1001.txt | Clean text invoice | PAID | $5,000.00 | none |
| invoice\_1002.txt | Typos ("Vndr", "Itms"), 20 GadgetX vs 5 in stock, $15,000 | REJECT |  | `STOCK_EXCEEDED` |
| invoice\_1003.txt | FakeItem at 0 stock, $100,000, "due yesterday", urgent wire language | REJECT |  | `ZERO_STOCK`, `INVALID_DUE_DATE`, `FRAUD_SUSPECTED` |
| invoice\_1004.json | Clean JSON, $1,890; approved and queued, then replaced by R1 before the batch | SUPERSEDED |  | `SUPERSEDED_BY_REVISION` |
| invoice\_1004\_revised.json | Revision of an unpaid invoice; adds 5 GadgetX; $5,940 passes every rule | PAID | $5,940.00 (full total) | `REVISION` (info) |
| invoice\_1005.json | 8 GadgetX vs 5; vendor address is 1600 Pennsylvania Ave | REJECT |  | `STOCK_EXCEEDED`, `SUSPICIOUS_ADDRESS` |
| invoice\_1006.csv | Key/value CSV with repeated keys | PAID | $2,750.00 | none |
| invoice\_1007.csv | MM/DD dates; WidgetA 20 vs 15, WidgetB 15 vs 10 | REJECT |  | `STOCK_EXCEEDED` |
| invoice\_1008.txt | Invoice inside an email; SuperGizmo and MegaSprocket not in DB | REJECT |  | `UNKNOWN_ITEM`, `UNKNOWN_VENDOR` |
| invoice\_1009.json | Empty vendor, null due date, qty -5, subtotal $1,000 vs lines -$250 | REJECT |  | `MISSING_VENDOR`, `INVALID_QUANTITY`, `MATH_MISMATCH`, `MISSING_DUE_DATE` |
| invoice\_1010.txt | WidgetA on 2 lines (12 total, within stock), rush price $300 vs $250, shipping line | NEEDS REVIEW |  | `PRICE_VARIANCE` |
| invoice\_1011.pdf | Clean PDF (first copy of 1011) | PAID | $3,000.00 | none |
| invoice\_1011.txt | Same invoice as the PDF | REJECT |  | `DUPLICATE` |
| invoice\_1012.pdf | OCR noise ("2O26", "$3,500.O0"), "Widget A", renamed vendor, $9,975 | PAID | $9,975.00 | `NEAR_THRESHOLD` (info) |
| invoice\_1012.txt | Same invoice as the PDF | REJECT |  | `DUPLICATE` |
| invoice\_1013.json | 8 lines, repeated SKUs: 22 WidgetA, 18 WidgetB, 9 GadgetX in total | REJECT |  | `STOCK_EXCEEDED` (aggregated) |
| invoice\_1013.pdf | Same invoice as the JSON | REJECT |  | `DUPLICATE` |
| invoice\_1014.xml | XML, EUR currency | PAID | EUR 4,125.00 at the configured rate | `CURRENCY_CONVERTED` (info) |
| invoice\_1015.csv | Clean tabular CSV | PAID | $6,500.00 | none |
| invoice\_1016.json | WidgetC not in DB | REJECT |  | `UNKNOWN_ITEM` |

**Beyond the golden suite**

- Unit tests for each parser, normalizer, validation check, and policy rule.
- Idempotency test: running the batch twice makes zero new payments.
- Adversarial cases to add: a prompt-injection line in invoice text, a total off by one cent, a vendor name with a lookalike character, and an empty file.

**Revision and payment scenarios** (built from copies of INV-1004 with edited totals)

| Scenario | Expected result |
| --- | --- |
| Revision arrives while the original is queued | Original Superseded, queued payment cancelled, revision queued for its full total |
| Revision arrives after the original was paid, higher total | Only the delta is queued, then paid in the next batch |
| Revision arrives after the original was paid, lower total | Held in Elevated Review as a credit or refund confirmation; nothing paid |
| Revision arrives after payment, same total | Recorded as Revised, no payment due |
| Revision of a queued invoice fails a rule | Original stays Superseded and unpaid; revision rejected or held |
| Idle trigger | Upload 3 files; no batch runs until all 3 finish and 60 seconds pass |
| Concurrent Pay all clicks | Second request gets 409; each row is paid once |
| Payment failure | Row shows Failed, retries next batch, moves to Elevated Review after 3 attempts |

## Assumptions, risks, and build order

**Assumptions** (state these in the README)

- **Stock means quantity received.** A supplier invoice normally adds stock, so we read the inventory table as a stand-in for a goods-received check: billed quantity must not exceed it. Stock is not decremented across a batch; otherwise INV-1001 then INV-1015 would wrongly fail on WidgetA.
- **Fail closed.** Anything the system can't extract or verify is held or rejected, never paid.
- **Revisions replace or top up.** A revision of an unpaid invoice replaces it and is paid for its full total. A revision of a paid invoice is checked as a whole under every normal rule; a higher total pays only the delta, and a lower total goes to a person to confirm a credit or refund with the vendor.
- **Reference prices** for the price-variance check are inferred from the clean invoices.
- **Fixed FX rate** from config; no live rates, per the no-internet rule.

**Risks and mitigations**

| Risk | Mitigation |
| --- | --- |
| LLM output varies between runs and between Grok and Claude | Temperature 0, Pydantic validation, rules engine owns the final outcome, recorded fixtures for tests |
| No API key or network during review | Offline mode runs the whole pipeline; README shows both modes |
| Prompt injection in invoice text | Text delimited and labeled untrusted; the LLM can't loosen an outcome |
| Scope creep past a day | P0 first and fully tested before any P1 work |
| Model name changes | `GROK_MODEL` and CLAUDE\_MODEL in config, confirmed before submission |
| Angular plus Python roughly doubles setup and build time, past the case's one-day guide | Angular Material for every table and dialog, one shared table component, polling before live updates, one make dev command starts both apps |
| A batch pays an invoice just as its revision arrives | The executor re-checks each row under the batch lock right before paying; a revision that lands mid-payment is handled as a revision of a paid invoice |

**Open questions**

- Should invoices in Awaiting review block the idle payment trigger? The spec says no; only invoices still being processed count.

**Build order**

1. Repo skeleton (`backend/`, `frontend/`), models, settings, DB seed.
2. Deterministic parsers and normalizers (F1, F2, F5, F6) with unit tests.
3. Validation checks and rules engine (F8, F9, F10, F14), then the golden test in offline mode.
4. LangGraph wiring with the review interrupt, payment queue, and rejection (F16, F17, F28), then the Payment Executor, batch triggers, and revision replacement (F38, F39), plus CLI and logs (F18, F19).
5. FastAPI endpoints and upload worker (F27), tested with the golden files.
6. Angular shell and sidebar, then Home, Queue, Elevated Review with its dialog, Payment Queue, Audit, and Payments (F21 to F26, F40), polling first.
7. LLM provider factory for Grok and Claude, extraction loop, validation tool calling, VP and Critic loop (F3, F4, F13, F15).
8. P1 features: live updates, detail drawer, fraud scoring, price variance, currency, tiles, frontend tests, one-command setup.
9. README with the architecture diagram, business-impact framing, screenshots of each page, and a demo GIF.
