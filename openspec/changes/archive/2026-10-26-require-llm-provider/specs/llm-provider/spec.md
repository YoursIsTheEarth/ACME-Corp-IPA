## MODIFIED Requirements

### Requirement: Provider selection by configuration (F36)
The system SHALL select the LLM provider for every agent from the `LLM_PROVIDER` setting, accepting only `grok` (default) or `claude`. A per-run override (the CLI's `--provider`) SHALL take precedence over the setting. Any other value, including the removed `offline`, SHALL stop startup with an error listing the valid values.

#### Scenario: Default provider
- **WHEN** `LLM_PROVIDER` is unset
- **THEN** agents receive a Grok model named by `GROK_MODEL`

#### Scenario: Claude selected
- **WHEN** `LLM_PROVIDER=claude`
- **THEN** agents receive a Claude model named by `CLAUDE_MODEL` (default `claude-sonnet-5-5`)

#### Scenario: Run override wins
- **WHEN** `LLM_PROVIDER=grok` and the run is started with provider override `claude`
- **THEN** every agent in that run uses the Claude model

#### Scenario: Invalid provider
- **WHEN** `LLM_PROVIDER=gpt`
- **THEN** startup stops with a message naming `grok` and `claude` as the valid values

#### Scenario: Offline no longer accepted
- **WHEN** `LLM_PROVIDER=offline`
- **THEN** startup stops with a message naming `grok` and `claude` as the valid values

### Requirement: Uniform model capabilities
Every provider SHALL support the two capabilities agents rely on: structured output into a given schema and tool binding. Models SHALL use temperature `LLM_TEMPERATURE` (default 0), timeout `LLM_TIMEOUT_S` (default 30), and up to `LLM_MAX_RETRIES` (default 3) retries with exponential backoff on rate-limit (429) and server (5xx) errors.

#### Scenario: Transient error retried
- **WHEN** a provider call returns 429 twice and then succeeds
- **THEN** the caller receives the successful result and the call is recorded with a retry count of 2

#### Scenario: Retries exhausted
- **WHEN** a provider call fails with 5xx on every attempt
- **THEN** an error is raised to the calling agent after `LLM_MAX_RETRIES` retries, and no outcome is fabricated

## REMOVED Requirements

### Requirement: Startup key check
**Reason**: Startup no longer stops when a key is missing (the API server must start so the web app can show the problem), and there is no keyless offline mode to exempt.
**Migration**: Replaced by "LLM key status": the key check is reported as a status and enforced by every entry point that processes invoices.

### Requirement: Offline rule-based model
**Reason**: The user decided the app must run on a real LLM. A rule-based stand-in let the pipeline appear to reason without a model, and hid hardcoded detection such as the suspicious-address list.
**Migration**: Set `LLM_PROVIDER=grok` with `XAI_API_KEY`, or `LLM_PROVIDER=claude` with `ANTHROPIC_API_KEY`. Tests use the test-only fake model (see "Test-only fake model").

## ADDED Requirements

### Requirement: LLM key status
The system SHALL determine whether the API key for each provider in use is set (`XAI_API_KEY` for Grok, `ANTHROPIC_API_KEY` for Claude) and SHALL report the result as a key status: whether every needed key is present, and the name of the first missing variable. No model SHALL be created and no LLM call SHALL be made while a needed key is missing. Every entry point that processes invoices SHALL check the key status before starting any run. There is no keyless mode.

#### Scenario: Missing Grok key
- **WHEN** `LLM_PROVIDER=grok` and `XAI_API_KEY` is unset
- **THEN** the key status reports that no key is configured and names `XAI_API_KEY`
- **AND** any attempt to process an invoice stops before a run starts

#### Scenario: Key present
- **WHEN** `LLM_PROVIDER=claude` and `ANTHROPIC_API_KEY` is set
- **THEN** the key status reports that the key is configured, with no missing variable

### Requirement: Test-only fake model
The test suite SHALL substitute a deterministic fake chat model for the real providers, so tests never call a paid API or need a network. The fake model SHALL support structured output and tool binding, and SHALL record LLM calls like a real provider. It SHALL be injectable only from tests. No setting, environment variable, or CLI flag SHALL select it.

#### Scenario: Tests make no provider calls
- **WHEN** the backend test suite runs with no network access
- **THEN** every test that exercises an agent receives the fake model, and no request reaches a provider API

#### Scenario: Fake is not selectable
- **WHEN** a user sets `LLM_PROVIDER` or `--provider` to any value naming the fake model
- **THEN** startup stops with a message naming `grok` and `claude` as the valid values
