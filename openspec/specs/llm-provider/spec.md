# llm-provider Specification

## Purpose
Lets every agent obtain a chat model for its role from one place, so Grok, Claude, or a fully offline rule-based model can be selected by configuration without changing agent code.

## Requirements

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

### Requirement: Active provider visible
The system SHALL expose the active provider and model name per agent role so the CLI, audit trail, and web app can display which model made each decision.

#### Scenario: Provider reported
- **WHEN** `LLM_PROVIDER=claude` and `CLAUDE_MODEL=claude-opus-5-5`
- **THEN** the reported active provider is `claude` and the model is `claude-opus-5-5` for every role

### Requirement: Per-agent provider overrides (F37, P1)
The system SHALL accept optional `LLM_PROVIDER_EXTRACTION`, `LLM_PROVIDER_VALIDATION`, `LLM_PROVIDER_APPROVAL`, and `LLM_PROVIDER_CRITIC` settings that override `LLM_PROVIDER` for that role only, so one provider can draft and another critique. The startup key check SHALL cover every provider in use.

#### Scenario: Cross-model critique
- **WHEN** `LLM_PROVIDER=grok` and `LLM_PROVIDER_CRITIC=claude`
- **THEN** the critic role receives a Claude model and all other roles receive Grok

#### Scenario: Override key checked
- **WHEN** `LLM_PROVIDER_CRITIC=claude` and `ANTHROPIC_API_KEY` is unset
- **THEN** startup stops with a message that `ANTHROPIC_API_KEY` is required

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
