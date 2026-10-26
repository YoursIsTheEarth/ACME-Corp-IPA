# llm-provider Specification

## Purpose
Lets every agent obtain a chat model for its role from one place, so Grok, Claude, or a fully offline rule-based model can be selected by configuration without changing agent code.

## Requirements

### Requirement: Provider selection by configuration (F36)
The system SHALL select the LLM provider for every agent from the `LLM_PROVIDER` setting, accepting `grok` (default), `claude`, or `offline`. A per-run override (the CLI's `--provider`) SHALL take precedence over the setting. Any other value SHALL stop startup with an error listing the valid values.

#### Scenario: Default provider
- **WHEN** `LLM_PROVIDER` is unset
- **THEN** agents receive a Grok model named by `GROK_MODEL`

#### Scenario: Claude selected
- **WHEN** `LLM_PROVIDER=claude`
- **THEN** agents receive a Claude model named by `CLAUDE_MODEL` (default `claude-sonnet-5-5`)

#### Scenario: Run override wins
- **WHEN** `LLM_PROVIDER=grok` and the run is started with provider override `offline`
- **THEN** every agent in that run uses the offline model

#### Scenario: Invalid provider
- **WHEN** `LLM_PROVIDER=gpt`
- **THEN** startup stops with a message naming `grok`, `claude`, and `offline` as valid values

### Requirement: Startup key check
The system SHALL verify at startup that the API key for each provider in use is set (`XAI_API_KEY` for Grok, `ANTHROPIC_API_KEY` for Claude) and SHALL stop with a clear message naming the missing variable if not. Offline mode SHALL require no key and no network.

#### Scenario: Missing Grok key
- **WHEN** `LLM_PROVIDER=grok` and `XAI_API_KEY` is unset
- **THEN** startup stops with a message that `XAI_API_KEY` is required, before any invoice is processed

#### Scenario: Offline needs nothing
- **WHEN** `LLM_PROVIDER=offline` with no keys set and no network
- **THEN** startup succeeds

### Requirement: Uniform model capabilities
Every provider, including offline, SHALL support the two capabilities agents rely on: structured output into a given schema and tool binding. Models SHALL use temperature `LLM_TEMPERATURE` (default 0), timeout `LLM_TIMEOUT_S` (default 30), and up to `LLM_MAX_RETRIES` (default 3) retries with exponential backoff on rate-limit (429) and server (5xx) errors.

#### Scenario: Transient error retried
- **WHEN** a provider call returns 429 twice and then succeeds
- **THEN** the caller receives the successful result and the call is recorded with a retry count of 2

#### Scenario: Retries exhausted
- **WHEN** a provider call fails with 5xx on every attempt
- **THEN** an error is raised to the calling agent after `LLM_MAX_RETRIES` retries, and no outcome is fabricated

### Requirement: Offline rule-based model
In offline mode the system SHALL provide a deterministic rule-based model with the same interface as the real providers: regex-based structured extraction for text invoices, template rationales, and a fixed tool-call plan. The same input SHALL always produce the same output.

#### Scenario: Deterministic offline output
- **WHEN** the offline model is asked twice for the same structured output with the same input
- **THEN** both results are identical

#### Scenario: Offline tool plan
- **WHEN** the offline model is bound to a set of tools and invoked
- **THEN** it returns tool calls following its fixed plan, then a final message with no tool calls

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
