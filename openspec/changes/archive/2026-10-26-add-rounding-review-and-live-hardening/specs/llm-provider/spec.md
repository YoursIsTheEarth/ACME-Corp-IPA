## MODIFIED Requirements

### Requirement: Uniform model capabilities
Every provider SHALL support the two capabilities agents rely on: structured output into a given schema and tool binding. Models SHALL use temperature `LLM_TEMPERATURE` (default 0) and timeout `LLM_TIMEOUT_S` (default 30). They SHALL make up to `LLM_MAX_RETRIES` (default 3) retries with exponential backoff on:
- rate-limit (429) errors
- server (5xx) errors
- request timeouts
- connection failures

Other client errors (such as 400, 401, or a proxy's 403) SHALL NOT be retried.

#### Scenario: Transient error retried
- **WHEN** a provider call returns 429 twice and then succeeds
- **THEN** the caller receives the successful result and the call is recorded with a retry count of 2

#### Scenario: Timeout retried
- **WHEN** a provider call times out once and then succeeds
- **THEN** the caller receives the successful result and the call is recorded with a retry count of 1

#### Scenario: Blocked request not retried
- **WHEN** a provider call fails with HTTP 403
- **THEN** the error is raised to the calling agent without a retry

#### Scenario: Retries exhausted
- **WHEN** a provider call fails with 5xx on every attempt
- **THEN** an error is raised to the calling agent after `LLM_MAX_RETRIES` retries, and no outcome is fabricated
