"""Test-only app factory for the Playwright e2e run: the real API with the fake model installed.

    XAI_API_KEY=test-key uvicorn fake_server:create_app --factory --app-dir backend/tests

Lives under tests/ only (see frontend/e2e/start-backend.sh); no setting or CLI flag selects the fake.
The dummy key makes the key status "configured"; no request ever reaches a provider.
"""

import pytest
from fastapi import FastAPI

import fake_llm
from acme.api import app


def create_app() -> FastAPI:
    fake_llm.install(pytest.MonkeyPatch())
    return app.create_app()
