# Design

## Context

See proposal.md for the motivation. This is how the current code is built:

- **Factory:** `acme.llm.factory.get_chat_model(role)` returns `RuleBasedLLM` when the provider is `offline`. That model answers structured-output calls from per-schema handlers and tool calls from a tool plan, both kept in global registries (`register_handler`, `register_tool_plan`).
- **Handler registrations:** the handlers are registered at import time from app modules:
  - `acme/ingestion/offline.py` (regex extraction)
  - `acme/approval/offline.py` (template Decision and Critique)
  - `acme/validation/agent.py` (`offline_tool_plan`)
  - `acme/normalization/llm_fallback.py` (empty Sku/Date suggestions)
- **Tests:** every suite sets `LLM_PROVIDER=offline` (root `conftest.py` autouse), and about 20 test files touch offline handlers. `workflow_helpers.restore_offline()` re-registers the defaults.
- **Key check:** `check_keys()` raises `ProviderConfigError`. The CLI calls it only for `--invoice_path` and `--batch`. The API calls it in the app lifespan, so today the server will not start without a key.
- **Address signal:** `acme/validation/checks.py: suspicious_address()` substring-matches `settings.suspicious_addresses` (default `["1600 Pennsylvania Ave"]`). `fraud_score()` and `fraud_signals()` use it.
- **API worker:** runs two job kinds, `process` (LLM) and `review` (resume after a human decision, no LLM). Startup `recover()` re-enqueues both kinds.
- **Front end and scripts:**
  - `frontend/e2e/start-backend.sh` starts a real backend with `LLM_PROVIDER=offline`.
  - The shell maps `offline` to "Offline" in the footer.
  - `run.sh` and `docker-compose.yml` default to offline when no key is set.

## Goals / Non-Goals

**Goals:**
- No code path in `backend/src` can produce an invoice outcome without a real provider.
- The missing-key state is explained in the same words everywhere: CLI, API, UI, and run scripts.
- Address plausibility is a model judgment with recorded reasoning. No address list remains in code or settings.
- The test suite stays deterministic, offline, and free.

**Non-Goals:**
- Recorded real-provider fixtures (the existing P2 F34). These are possible later and not needed here.
- Making any other deterministic check LLM-driven.
- Changing the approval policy, fraud weights, or threshold (the `suspicious_address` weight stays 0.30).

## Decisions

### D1. User decision: no keyless mode, despite the case README

The case README says "Runtime: Assume no internet for external APIs — simulate everything locally" and "Other models are acceptable if you don't have an API key." The original design read that as a requirement for an offline LLM. The user has decided otherwise: the app must run on Grok or Claude, and it explains clearly what is missing when no key is set.

What this means:
- A reviewer needs an API key and network access to `api.x.ai` or `api.anthropic.com` to see invoices processed.
- Without a key they can still open the UI, browse existing data, decide held invoices, and run payments.
- The README must say this up front.
- Mock payment and inventory stay local. "External APIs" in the case README still holds for banking.

### D2. Key status instead of a startup crash

`acme.llm` gains `key_status() -> KeyStatus(configured: bool, provider: str, missing_key: str | None)`, computed over every provider in use (per-role overrides included). Two more functions build on it:
- `require_llm()` raises `ProviderConfigError` with a standard message.
- `missing_key_message(env_name, provider)` builds that message: "No LLM token provided: set XAI_API_KEY for Grok (in .env or the environment). The app cannot process invoices without it."

How each entry point uses it:
- **CLI:** keeps its pre-run check (exit code 2) and uses the new message. `--json` prints `{"error": ..., "missing_key": ...}`.
- **API:** the lifespan no longer calls `check_keys()`. It still validates the provider value, so an invalid provider stops startup. The upload router calls `key_status()` per request and returns 503 `llm_not_configured`.
- **Recovery:** while no key is set, `recover()` and the CLI's `_recover` re-enqueue only `review` jobs. Process jobs wait for a restart with a key.
- `get_chat_model` calls `require_llm()` as a last line of defense.

Alternative considered: keep the hard startup failure for the API. Rejected, because the user wants the UI to load and show the error.

503 rather than 400, 409, or 422 because the request is valid and the service is temporarily unable to process it because of server configuration. The client can retry once the server is fixed.

### D3. Address plausibility as a dedicated structured-output call

New module `acme/validation/address.py`:
- **Model:** `AddressAssessment(plausible: bool, reason: str, confidence: float 0..1)`, a Pydantic model.
- **Function:** `assess_address(invoice) -> AddressAssessment | None`. It returns `None` when the invoice has no vendor address.
- **Call:** it uses `get_chat_model("validation").with_structured_output(AddressAssessment)`, sends the address and vendor name inside the existing untrusted-data delimiters, and uses prompt `prompts/address_v1.md` with `prompt_version` `address_v1`.

`run_validation` calls it once, before the tool loop, and stores the verdict on `ValidationContext` (`ctx.address_assessment`). Two things read it:
- `fraud_signals()` raises `SUSPICIOUS_ADDRESS` from the stored verdict. The finding has `source` = `llm` and evidence `{address, reason, confidence}`, and is capped at WARNING by the existing rule.
- `fraud_score()` treats `suspicious_address` as present when the verdict is implausible.

`run_checks(invoice, ctx)` with no assessment on the context raises no address signal. Callers that bypass the LLM therefore see no address finding, which is correct.

Alternative considered: a tool the validation LLM may call. Rejected, because the spec requires the assessment to run every time and the tool loop lets the model skip tools. A forced pre-call is simpler than "the deterministic sweep calls the LLM".

Failure: if the call fails after retries, the error propagates like any other validation LLM failure, so the run fails closed and is not paid. No verdict is invented.

### D4. Fake model lives in the tests

- **Removed from the app:** `RuleBasedLLM`, the registries, and every `offline.py` module move out of `backend/src`.
- **New test module:** `backend/tests/fake_llm.py` holds:
  - `FakeChatModel`: structured output plus `bind_tools`, and it fires the same callbacks so `llm_calls` rows are recorded with provider `fake`.
  - the moved handlers: regex extraction, template approval/critic, the call-every-tool plan, null SKU/date suggestions.
  - a new `address_verdict` handler.
- **Address handler:** returns implausible for addresses in a small test-local landmark table (it includes "1600 Pennsylvania Ave"), and plausible otherwise. This table is test data, not app logic.
- **Injection:** `get_chat_model` builds models through a private `_build_model(provider, model, settings, callbacks)`. The root `conftest.py` autouse fixture:
  - sets `LLM_PROVIDER=grok` and `XAI_API_KEY=test-key`, so key status is configured
  - monkeypatches `acme.llm.factory._build_model` to return `FakeChatModel(callbacks=...)`

  Tests that need the missing-key path unset the key and skip the patch. No setting or CLI flag reaches the fake.
- **e2e:** the Playwright run needs a live backend. A test-only app factory, `backend/tests/fake_server.py: create_app()`, applies the same patch and calls `acme.api.app.create_app()`. `start-backend.sh` runs `uvicorn fake_server:create_app --factory --app-dir backend/tests` with a dummy key.

Alternatives considered:
- **A hidden `LLM_PROVIDER=test` value:** rejected, because it is just offline mode again.
- **`respx` HTTP mocking of the provider SDKs:** rejected as brittle across the xAI and Anthropic SDKs.

### D5. Settings and migration of existing configuration

- `Settings.suspicious_addresses` is deleted. An old `SUSPICIOUS_ADDRESSES` entry in a `.env` is ignored, because pydantic-settings ignores extra keys (verify the model's `extra` config; set `ignore` if needed).
- `PROVIDERS = ("grok", "claude")`. `LLM_PROVIDER=offline` now fails provider validation with "valid values are: grok, claude (offline mode was removed; set XAI_API_KEY or ANTHROPIC_API_KEY)".
- `active_models()` no longer knows an offline model name.
- The data model's `FindingSource` gains no new value, because `llm` already exists.

### D6. Scripts

- `run.sh`: remove the offline fallback. Before starting, run `"$PY" -m acme.llm` (a new `__main__` that prints the key status). If no key is configured, print a yellow warning naming the variable and continue, because the servers must still start.
- `Makefile dev`: same warning.
- `docker-compose.yml`: no `LLM_PROVIDER` default; pass `XAI_API_KEY` and `ANTHROPIC_API_KEY` through from the environment or `.env`.
- `.env.example`: drop `offline` from the comment and remove `SUSPICIOUS_ADDRESSES`.

## Risks / Trade-offs

- [Reviewers without a key can't see processing] → The README leads with key setup. The UI banner and CLI message say exactly what to set. A reviewer can still run the full deterministic and golden test suite with no key.
- [LLM address verdicts vary between runs and providers] → Temperature 0. The finding is WARNING only (it can route to review, never reject on its own). The reason is stored as evidence for the reviewer.
- [Golden test now depends on the fake's address table] → That's acceptable for a regression suite. Real-model behavior on INV-1005 is checked by a manual step in tasks and, later, by recorded fixtures (P2).
- [One extra LLM call per invoice] → Small and bounded: one structured call, recorded in `llm_calls`. Invoices with no address skip it.
- [Firewall blocks provider hosts in sandboxed setups] → Document the 403 approval flow next to the key setup in the README.

## Migration Plan

1. Land the backend and test changes together: removing the offline model breaks every test until the fake is injected.
2. Update the scripts, docs, front end, and e2e harness.
3. Anyone with `LLM_PROVIDER=offline` in `.env` gets a startup error naming the valid values. Remove the line and add a key.

Rollback: revert the change commit. Nothing in the data or schema changes.

## Open Questions

- Confirm the exact current Grok model name before submission. This is carried over from the foundation and unaffected here.

## Implementation notes

- **Fake model wiring.** `backend/tests/fake_llm.py` holds `FakeChatModel`, the handler and tool-plan registries, and the moved handlers (regex extraction, template approval/critic, call-every-check tool plan, null SKU/date suggestions) plus `address_verdict`, backed by a test-local landmark table. `install(monkeypatch)` replaces `acme.llm.factory._build_model` and resets the registries. The calls it makes are recorded in `llm_calls` with provider `fake`, model `fake-model`. Traces and `decided_by` still show the configured provider (`grok`/`grok-4`), because `active_models()` reports settings.
  - Root `conftest.py` (autouse): sets `LLM_PROVIDER=grok` and `XAI_API_KEY=test-key`, then installs the fake. The `real_models` fixture restores the real builder for the tests that check the Grok and Claude classes. No calls are made in those tests.
  - Session- and module-scoped fixtures (`test_golden.py`, `api/conftest.py::api_golden`) install the fake on their own `MonkeyPatch`.
  - Two test-only entry points live under `backend/tests/` and install the same fake with a standalone `pytest.MonkeyPatch()`. Neither ships in `backend/src`, and no setting or flag reaches them. `LLM_PROVIDER=fake` and `LLM_PROVIDER=offline` are rejected like any invalid value.
    - `fake_server.py: create_app()`: e2e. `frontend/e2e/start-backend.sh` runs `uvicorn fake_server:create_app --factory --app-dir backend/tests` with `XAI_API_KEY=test-key`.
    - `fake_cli.py`: the subprocess CLI tests that need a fresh process, such as the README command and held-invoice-survives-restart.
- **Address module import.** `acme/validation/address.py` imports `untrusted()` lazily from `acme.validation.agent`, because the agent imports the address module.
- **Invalid-provider message.** It keeps the design's wording, which includes "offline mode was removed". That is the one `offline` hit in `backend/src` (task 2.2's grep).
- **CLI.** `--provider` uses argparse `choices`, so an invalid value exits 2 via argparse ("choose from grok, claude"). An invalid `LLM_PROVIDER` setting now stops every CLI command, not only processing.
- **Recovery.** Without a key, `recover()` and the CLI's `_recover` still reset orphaned runs to Uploaded but do not process them. A restart with a key processes them.
- **Front end.** `upload.service.ts` needed no change. Its `errorMessage()` already shows `detail.message`, and a component test covers the 503.
- **Network check.** The backend suite also passed with every HTTP(S) proxy pointed at a closed port.
- **Real-model check (8.1).** No real API key was available in this environment, so the INV-1005 live run was not performed. The no-key paths were verified for real:
  - `main.py` exits 2 with the message.
  - The API returns 503 and `/api/stats` reports `configured: false`.
  - `./run.sh` with empty keys starts both servers, prints the yellow warning, and the browser shows the banner and the disabled drop zone.
