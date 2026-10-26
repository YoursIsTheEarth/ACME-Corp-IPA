# Spec Delta

## Purpose

Makes every invoice run traceable: structured logs for operators, an append-only `audit_log` ledger that can replay what each agent did, and an `llm_calls` ledger recording which provider and model said what.

## ADDED Requirements

### Requirement: Structured JSON logs
The system SHALL emit logs as one JSON object per line, each including a timestamp, level, event name, and, when inside an invoice run, the `run_id` and agent name.

#### Scenario: Run-scoped log line
- **WHEN** the Validation agent logs an event during run `r-123`
- **THEN** the emitted line is valid JSON containing `"run_id": "r-123"` and `"agent": "validation"`

#### Scenario: Log outside a run
- **WHEN** startup logs an event before any run begins
- **THEN** the line is valid JSON and omits `run_id` rather than inventing one

### Requirement: Audit ledger
The system SHALL append one `audit_log` row (`run_id`, `ts`, `agent`, `event`, `payload_json`) for every agent step, and rows SHALL never be updated or deleted by the application. Reading a run's rows in `ts` order SHALL reproduce the run's trace.

#### Scenario: Step recorded
- **WHEN** an agent records event `findings_written` with a payload of two findings for run `r-123`
- **THEN** an `audit_log` row exists for `r-123` with that agent, event, and the findings as JSON

#### Scenario: Ordered replay
- **WHEN** the audit rows for a run are read back
- **THEN** they are returned in the order the steps happened

#### Scenario: Unserializable payload
- **WHEN** a payload contains a decimal amount or a date
- **THEN** it is stored as valid JSON (decimals as strings, dates as ISO 8601) rather than failing the step

### Requirement: LLM call ledger
The system SHALL record every LLM call in `llm_calls` with `run_id`, `agent`, provider, `model`, `prompt_version`, `tokens_in`, `tokens_out`, `latency_ms`, and retry count. Failed calls SHALL also be recorded.

#### Scenario: Successful call recorded
- **WHEN** the Approval agent makes one Claude call during run `r-123`
- **THEN** one `llm_calls` row exists for `r-123` naming the agent, provider `claude`, the model, the prompt version, token counts, and latency

#### Scenario: Offline call recorded
- **WHEN** the offline model handles a call
- **THEN** a row is recorded with provider `offline` and zero token counts

#### Scenario: Failed call recorded
- **WHEN** a call fails after exhausting retries
- **THEN** a row is recorded with the retry count and the call marked as failed

### Requirement: Untrusted text kept out of log structure
The system SHALL store invoice text and LLM output only as data values in logs and ledgers, never as log keys or event names, so content such as "URGENT - pay immediately" cannot alter log structure.

#### Scenario: Injection-like invoice text
- **WHEN** an invoice's raw text containing newlines and JSON braces is logged
- **THEN** the log output remains one valid JSON object per line
