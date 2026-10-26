# Tasks

## 1. Test-only fake model (lands first, so the suite stays green)

- [ ] 1.1 Create `backend/tests/fake_llm.py` with `FakeChatModel` (structured output plus `bind_tools`, firing the passed callbacks) and per-schema handler and tool-plan registries, moving the logic out of `acme/llm/offline.py`. Verify a unit test that structured output and a tool plan behave as before and that an `llm_calls` row is recorded with provider `fake`.
- [ ] 1.2 Move the handlers into `fake_llm.py`:
  - regex extraction from `acme/ingestion/offline.py`
  - template Decision/Critique from `acme/approval/offline.py`
  - `offline_tool_plan` from `acme/validation/agent.py`
  - null Sku/Date suggestions from `acme/normalization/llm_fallback.py`

  Add an `AddressAssessment` handler backed by a test-local landmark table (including "1600 Pennsylvania Ave"). Verify `pytest backend/tests/ingestion backend/tests/approval` still passes once 1.3 is in.
- [ ] 1.3 Add `_build_model(provider, model, settings, callbacks)` to `acme/llm/factory.py`. In the root `backend/tests/conftest.py`:
  - set `LLM_PROVIDER=grok` and `XAI_API_KEY=test-key`
  - monkeypatch `_build_model` to return `FakeChatModel`
  - replace `workflow_helpers.restore_offline()` and the per-suite `register_offline` fixtures (api, approval, validation, workflow conftests) with fake-registry resets

  Verify that the full `pytest backend/tests` passes with no request to any provider host (run with network blocked, or assert `RetryingChatXAI` is never instantiated).

## 2. Remove offline mode from the app

- [ ] 2.1 Change `acme/llm/factory.py` so that:
  - `PROVIDERS = ("grok", "claude")`, and the invalid-provider message names grok and claude and notes offline was removed
  - the `offline` branches in `get_chat_model`, `_model_name`, and `active_models` are gone

  Delete `acme/llm/offline.py` and its exports from `acme/llm/__init__.py`. Verify `test_llm.py` covers that `LLM_PROVIDER=offline` and `--provider offline` are both rejected naming `grok` and `claude`.
- [ ] 2.2 Remove the app-side offline modules and registrations: `acme/ingestion/offline.py` (and the import in `ingestion/service.py`), `acme/approval/offline.py` (and the call in `approval/agent.py`), `register_offline` in `validation/agent.py`, and the `register_handler` calls in `normalization/llm_fallback.py`. Verify `grep -rn "offline\|register_handler\|RuleBased" backend/src` returns nothing and the suite passes.
- [ ] 2.3 Add `key_status()`, `require_llm()`, `missing_key_message()`, and a `python -m acme.llm` status printer to `acme/llm`. `get_chat_model` calls `require_llm()`. Verify unit tests for:
  - the configured, missing-Grok-key, and missing-Claude-key cases
  - a per-role override needing the other key
  - the exact message text naming the variable and stating invoices cannot be processed

## 3. LLM address plausibility

- [ ] 3.1 Add `acme/validation/address.py` (`AddressAssessment` model and `assess_address(invoice)`) and `backend/prompts/address_v1.md`: untrusted-data delimiters, criteria for implausible supplier addresses, and one or two few-shot examples. Verify unit tests that:
  - no address means no call
  - the prompt wraps the address in the untrusted delimiters
  - an `llm_calls` row is recorded with `prompt_version` `address_v1`
- [ ] 3.2 In `run_validation`, call `assess_address` once before the tool loop and store the verdict on `ValidationContext`. Make `fraud_signals()` and `fraud_score()` use the stored verdict:
  - WARNING `SUSPICIOUS_ADDRESS` with `source` = `llm` and evidence `{address, reason, confidence}`
  - no finding when the verdict is plausible or missing

  Delete `suspicious_address()` and `Settings.suspicious_addresses`, and confirm extra env keys are ignored. Verify tests for:
  - INV-1005 is flagged with source `llm`
  - a clean invoice is not flagged
  - an assessment that is never asked for in the tool loop still applies
  - a plausible verdict doesn't clear a CRITICAL finding
  - INV-1005 alone does not trip `FRAUD_SUSPECTED`
  - `grep -rn suspicious_addresses backend/src` returns nothing
- [ ] 3.3 Update the fraud and validation tests that relied on the list (`backend/tests/validation/`). Verify the golden suite (`backend/tests/test_golden.py`) passes all 20 rows, with INV-1005's `SUSPICIOUS_ADDRESS` from source `llm`.

## 4. CLI

- [ ] 4.1 In `acme/cli.py`:
  - `--provider` choices become grok and claude
  - the pre-run check uses `missing_key_message` and exits 2 before creating a run
  - `--json` prints `{"error", "missing_key"}`
  - `_recover` skips re-processing orphaned runs when no key is set
  - the help text drops offline

  Verify CLI tests:
  - the README command with no key prints the message naming `XAI_API_KEY` and creates no run
  - Claude without `ANTHROPIC_API_KEY`
  - JSON error output
  - `--explain`, `review`, and `payments run` succeed with no key
  - `--provider offline` is rejected

## 5. Backend API

- [ ] 5.1 In `acme/api/app.py`, the lifespan validates the provider value but no longer calls `check_keys()`. `recover()` re-enqueues only `review` jobs while no key is set. Verify API tests:
  - the app starts with no key
  - an invalid provider still fails startup
  - an Uploaded run stays Uploaded across a keyless restart and is processed after a restart with a key
- [ ] 5.2 The upload router returns 503 `{"detail": {"code": "llm_not_configured", "message", "missing_key"}}` before storing files or creating runs while the key is missing. Verify a test that nothing is stored or created, and that review and payment execution still work with no key.
- [ ] 5.3 `/api/stats` adds `llm.configured` and `llm.missing_key`. Verify tests for both states. Update `backend/README.md` "Web API" with the 503 shape and the new stats fields.

## 6. Web app

- [ ] 6.1 Front-end display changes:
  - add `configured` and `missing_key` to the `llm` type in `frontend/src/app/core/api.models.ts`
  - remove `offline` from `PROVIDER_LABELS` in `shell.component.ts`
  - add the persistent error banner to the shell, reading "No LLM token provided — the app cannot process invoices without it", naming the variable and saying to set it in `.env` and restart the backend

  Verify a component test for the banner being shown and hidden, driven by stats.
- [ ] 6.2 Disable the Home drop zone and Browse button while not configured, showing the same explanation. Map an upload 503 to the API's message in `upload.service.ts`. Verify component tests for the drop-zone disabled state and the 503 message.
- [ ] 6.3 Add `backend/tests/fake_server.py` (an app factory installing the fake model). Point `frontend/e2e/start-backend.sh` at it with a dummy key and no `LLM_PROVIDER=offline`. Verify the Playwright happy path passes.

## 7. Scripts and docs

- [ ] 7.1 `run.sh` and `Makefile dev`: remove the offline fallback, and print the key-status warning via `python -m acme.llm` while still starting both servers. Verify that running `./run.sh` with no key starts both servers, prints the warning, and the UI shows the banner (manual check, then stop).
- [ ] 7.2 Update `docker-compose.yml` (no offline default; pass the keys through) and `.env.example` (drop `offline` and `SUSPICIOUS_ADDRESSES`). Verify `docker compose config` renders without offline.
- [ ] 7.3 Update `README.md`, `backend/README.md`, and `frontend/README.md`:
  - remove every offline instruction and `--provider offline` example
  - add a "Configure an LLM key" section at the top, with the firewall/403 note
  - state the D1 decision and its consequence for reviewers

  Verify `grep -rn -i offline README.md backend/README.md frontend/README.md` returns only the sentence explaining that offline mode was removed.

## 8. Integration check

- [ ] 8.1 Run the full `pytest backend/tests`, `npm --prefix frontend run test:ci`, and `make e2e`, and verify all pass. With a real key, if one is available, run `python main.py --invoice_path=data/invoices/invoice_1005.json` and verify `SUSPICIOUS_ADDRESS` (source `llm`) with the model's reason. Record the result, or that no key was available, in this change's design.md under "Implementation notes".
