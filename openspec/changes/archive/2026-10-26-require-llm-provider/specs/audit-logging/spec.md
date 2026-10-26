## REMOVED Requirements

### Requirement: LLM call ledger
**Reason**: Its "Offline call recorded" scenario describes the removed offline model.
**Migration**: Replaced by "LLM call record", which keeps every other behavior and adds the address-assessment call.

## ADDED Requirements

### Requirement: LLM call record
The system SHALL record every LLM call in `llm_calls` with `run_id`, `agent`, provider, `model`, `prompt_version`, `tokens_in`, `tokens_out`, `latency_ms`, and retry count. Failed calls SHALL also be recorded.

#### Scenario: Successful call recorded
- **WHEN** the Approval agent makes one Claude call during run `r-123`
- **THEN** one `llm_calls` row exists for `r-123` naming the agent, provider `claude`, the model, the prompt version, token counts, and latency

#### Scenario: Address assessment recorded
- **WHEN** the Validation stage assesses a vendor address during run `r-123`
- **THEN** one `llm_calls` row exists for `r-123` with agent `validation` and the address-assessment prompt version

#### Scenario: Failed call recorded
- **WHEN** a call fails after exhausting retries
- **THEN** a row is recorded with the retry count and the call marked as failed
