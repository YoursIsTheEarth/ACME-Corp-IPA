# Design

## Context

This change runs after normalization and before disposition. Its input is a canonical `Invoice`, from `add-invoice-ingestion`, with these properties:
- SKUs are resolved where possible, and unmatched lines keep `sku = None` and their `raw_name`.
- Dates are parsed, or flagged as relative or unparseable.
- Amounts are in USD, with the original currency kept.

The models (`Finding`, `Decision`, `Critique`, `InvoiceState`), the tables (`inventory`, `vendors`, `processed_invoices`), and `get_chat_model(role)` all come from `add-project-foundation`. `add-agent-workflow` wires these agents into the `StateGraph` and owns routing. `add-payment-processing` owns everything that happens to money after a `Decision`. For motivation, see proposal.md.

The source of truth is the design spec at the repo root, including its test plan. Requirements and scenarios are in `specs/invoice-validation` and `specs/invoice-approval`.

## Goals / Non-Goals

**Goals:**
- Checks are pure, so each one can be unit-tested with an in-memory `Invoice` and a seeded SQLite fixture.
- The validation results are identical in offline, Grok, and Claude modes. Only the narrative changes.
- The golden-file outcomes depend only on deterministic code.

**Non-Goals:**
- Graph routing, the review `interrupt()`, payment queueing, and supersede logic. These belong to `add-agent-workflow` and `add-payment-processing`.
- Writing to `processed_invoices`. Disposition does this, and this change only reads it.
- Learned or statistical fraud models. The fraud score is a fixed weighted sum.

## Decisions

### D1. Module layout
- `backend/src/acme/validation/checks.py` has one pure function per check. Each takes `(invoice, ctx)` and returns `list[Finding]`. `ctx` is a small read-only lookup object over `inventory`, `vendors`, `processed_invoices`, and `payments`.
- `validation/tools.py` defines LangChain `@tool` wrappers over the checks: `lookup_item`, `check_stock`, `reconcile_math`, `check_integrity`, `check_duplicate`, `check_vendor`, `fraud_signals`, and `check_prices`.
- `validation/agent.py` defines `run_validation(state) -> state`.
- `approval/policy.py` defines `apply_policy(invoice, findings, revision_ctx) -> PolicyResult`.
- `approval/agent.py` defines `run_approval(state) -> state`, which contains the VP and Critic loop.

The design spec lists six validation tools. `check_integrity` (vendor, due-date, and quantity checks) and `check_prices` (F12) are added so that every check is callable as a tool and none hides inside another check.

*Alternative considered:* one large `validate()` function. It was rejected because it is harder to test and gives the LLM nothing meaningful to choose between.

### D2. Validation agent is an internal loop, exposed as one node
`run_validation` runs its own loop: bind the tools, invoke the model, execute the requested tools, and repeat. The loop is capped at 8 rounds, and the agent then runs the deterministic sweep. `add-agent-workflow` mounts it as a single node, or as a subgraph with a `ToolNode` if that change prefers. The contract is the same either way: `state.findings` holds the de-duplicated union of LLM-requested results, the sweep results, and capped `llm` judgment findings.

The sweep keeps a record of which check functions ran, so a check the LLM already called is not run a second time. De-duplication uses the key `(code, json(evidence))`.

### D3. Severity table lives in one place
A single map in `validation/codes.py` sets the severity for each code:

| Code | Severity |
| --- | --- |
| `UNKNOWN_ITEM`, `ZERO_STOCK`, `STOCK_EXCEEDED`, `INVALID_QUANTITY`, `MATH_MISMATCH`, `MISSING_VENDOR`, `DUPLICATE`, `FRAUD_SUSPECTED` | CRITICAL |
| `UNKNOWN_VENDOR`, `MISSING_DUE_DATE`, `INVALID_DUE_DATE`, `DUE_BEFORE_INVOICE_DATE`, `PRICE_VARIANCE`, `SUSPICIOUS_ADDRESS`, `REVISION_CREDIT_DUE`, `INVOICE_NUMBER_REUSED` | WARNING |
| `REVISION`, `NEAR_THRESHOLD`, `CURRENCY_CONVERTED` | INFO |

`CURRENCY_CONVERTED` is emitted by normalization. It appears here only so the rules engine treats it as INFO.

The spec's CRITICAL list does not mention due dates. Missing or invalid due dates are therefore WARNING, which still fails closed through review. INV-1003 and INV-1009 are rejected by their other CRITICAL findings.

### D4. Revision context computed once
`check_duplicate` returns either a finding or a `RevisionContext`. The context records the original's `run_id`, its outcome, `paid` (true when a row in `payments` matches the original's idempotency key), its total, and its revision. It is stored on the state so `apply_policy` and `add-payment-processing` can read it, and neither has to query a second time.

The duplicate key is the normalized vendor, `invoice_number`, revision, and total. A missing revision is treated as R0.

### D5. Fraud scoring as a configurable weighted sum (P1)
The weights and threshold are settings, with these defaults:

| Signal | Weight |
| --- | --- |
| Urgency language | 0.25 |
| Wire-transfer request | 0.25 |
| "Immediate" terms | 0.15 |
| Relative or pre-invoice due date | 0.15 |
| Unknown vendor | 0.20 |
| Suspicious address | 0.30 |
| Near threshold | 0.10 |

The threshold is 0.60. Checked against the invoices:
- INV-1003 scores 1.00.
- INV-1005 scores 0.30.
- INV-1008 scores 0.30.
- INV-1012 scores 0.10.

Urgency and wire terms are matched by case-insensitive regex over the notes and payment terms. The LLM can add a judgment signal as a WARNING finding, but that signal never adds to the score. Past-due is measured against the invoice date, not today, because every sample invoice is from 2026-01 and would otherwise score as past due.

### D6. Price variance compared in USD (P1)
The billed unit price is converted with the same fixed FX rate that normalization uses, then compared with `inventory.unit_price`. A deviation strictly greater than 10% is flagged.

INV-1014 bills WidgetA at EUR 225 and WidgetB at EUR 475. It passes only if the configured EUR→USD rate is between 1.00 and 1.158. This constraint is recorded in tasks so that `add-invoice-ingestion` picks a rate in that range.

### D7. Approval: floor first, LLM second, clamp last
`run_approval` runs in four steps:
1. Call `apply_policy`.
2. Ask the LLM for a structured `Decision` (`with_structured_output(Decision)`), giving it the invoice, the findings, the floor, and the fired rules.
3. If VP scrutiny is required, run the Critic (`with_structured_output(Critique)`, which may call `apply_policy` as a tool) and revise for up to 2 rounds.
4. Clamp the result with `final = max(floor, llm_outcome, critic_suggested)`, using the strictness order.

When the floor is REJECT or the result is auto-approval, there is a single LLM call for the rationale and no critic. This keeps runs under 30 s per invoice, and the critic adds value only where the LLM can change the outcome.

The Critic's `suggested_outcome` goes through the same clamp. A critic cannot loosen an outcome either.

*Alternative considered:* running the critic on every invoice. It was rejected because it doubles LLM cost for decisions the rules have already fixed.

### D8. Offline behavior
`RuleBasedLLM`, from `add-project-foundation`, needs three behaviors for this change:
- Validation: a fixed tool plan that calls every tool once, then stops.
- Approval: a template rationale built from the fired rules.
- Critic: passes when the draft outcome is at least the floor and the rationale names every fired rule.

These behaviors are specified here and implemented in the provider module.

### D9. Prompts
`backend/prompts/validation_v1.md`, `approval_v1.md`, and `critic_v1.md` are versioned prompts. Each has a system role, the schema, and one or two few-shot examples drawn from INV-1001 and INV-1006. The invoice JSON or text is wrapped in `<untrusted_invoice>…</untrusted_invoice>`. The prompt version is logged with each LLM call.

## Risks / Trade-offs

- **The LLM skips tools or hallucinates findings.** → The deterministic sweep runs anyway, and LLM findings are capped at WARNING.
- **No golden file reaches the VP scrutiny path.** Every invoice over $10K is rejected. → Add synthetic fixtures for "clean over $10K", "critic never passes", and "LLM tries to loosen".
- **The golden outcomes depend on P1 features.** INV-1010 needs F12 to reach NEEDS REVIEW. Without it, INV-1010 is auto-approved and paid, which counts as a bad payment. INV-1003's expected `FRAUD_SUSPECTED` needs F11. → Schedule F11 and F12 immediately after P0 in this change, before the golden suite gates.
- **The vendor seed is incomplete.** If an approved golden vendor is missing from `vendors`, `UNKNOWN_VENDOR` (WARNING) sends a clean invoice to review. → Tasks include a check that every vendor of a golden PAID invoice is seeded as approved, including QuickShip's former name as an alias.
- **The suspicious-address list is fragile.** INV-1004 uses "742 Evergreen Terrace, Springfield", a fictional address, and the test plan still expects it to pass. → The default denylist contains only 1600 Pennsylvania Ave. Extending it requires re-running the golden suite.
- **The FX rate breaks INV-1014.** → See D6, and add a unit test that pins the allowed range.

## Open Questions

- Should `UNKNOWN_VENDOR` alone send an otherwise clean invoice to review (the current choice), or only feed the fraud score? No golden file distinguishes the two, so this can be tuned later without changing the tasks.

## Implementation notes

- **Entry points.** `acme.validation.run_validation(state, ctx=None) -> InvoiceState` and `acme.approval.run_approval(state) -> InvoiceState` both return a new state; each appends `{"agent", "event", ...}` entries to `state.trace` and mirrors them to `audit_log`. `acme.validation.run_checks(invoice, ctx)` runs every deterministic check without an LLM. `acme.approval.apply_policy(invoice, findings, revision_ctx) -> PolicyResult(floor, rules, fraud, vp_scrutiny)`; rule ids are `CRITICAL_<CODE>`, `WARNING_<CODE>`, `REVISION_OF_PAID_INVOICE_LOWER_TOTAL`, `VP_SCRUTINY_OVER_THRESHOLD`, `AUTO_APPROVE_AT_OR_UNDER_THRESHOLD`.
- **Shared model additions** (in `acme.models`, backward compatible): `Decision.decided_by` ("Auto (rules)" or "AI VP (provider/model)"; review sets a name), `RevisionContext`, and `InvoiceState.revision_context` (D4's "stored on the state").
- **Tools.** The eight checks in D1 plus `report_finding`, the only way the LLM adds a judgment finding (stored `source=llm`, CRITICAL capped to WARNING). Check tools take no arguments; they are bound to the invoice under validation. `SUSPICIOUS_ADDRESS` and `NEAR_THRESHOLD` are emitted by `fraud_signals`.
- **`processed_invoices` contract.** Validation only reads. The writer (disposition) stores `vendor = ValidationContext.vendor_key(invoice.vendor_name)` (approved vendor with aliases folded in, else the trimmed, case-folded name) and `content_hash = acme.validation.content_hash(invoice)` (number, revision, total, and lines; format-independent), for every outcome. The original's total is read from `invoice_runs.total_usd` via `run_id`. Duplicate = same vendor/number/revision and same content hash (or same total when no hash is stored). Paid status comes from `payments` rows whose key ends in `|<invoice_number>|<revision>` (optionally `|delta`) and whose vendor maps to the same vendor key.
- **Due dates.** A relative due date ("yesterday") is `INVALID_DUE_DATE` and counts as the fraud signal; no due-date check reads the clock.
- **FX bound.** INV-1014's WidgetB crosses +10% just above 1.1578 USD/EUR, so the tested upper bound is 1.157 (D6's 1.158 rounds up).
- **Golden data.** INV-1007 and INV-1013 also raise `MATH_MISMATCH` (their stated totals are off by $110.00 and $50.00); both are rejected anyway. Hand-coded golden invoices live in `backend/tests/golden_invoices.py` with `record_processed`/`record_payment` stand-ins for disposition.
- **Offline.** `acme.validation.agent.register_offline()` installs the tool plan (every check, never `report_finding`); `acme.approval.offline.register_offline()` installs the `Decision` template and `Critique` rule checker. Both run on import; tests re-register them because other suites replace the global registries.
- **Prompts** are `backend/prompts/{validation,approval,critic}_v1.md`, logged as prompt versions `validation_v1`, `approval_v1`, `critic_v1`.
