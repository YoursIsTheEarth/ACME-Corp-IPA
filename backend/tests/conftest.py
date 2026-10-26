"""Every test runs in an empty temp directory with a dummy Grok key and the test-only fake model.

No test reaches a provider API: `acme.llm.factory._build_model` returns `fake_llm.FakeChatModel`.
Tests of the missing-key path delete `XAI_API_KEY`; tests of the real model classes use `real_models`.
"""

import pytest

from acme.db import connect, init_schema
from acme.db.seed import seed
from acme.llm import factory
from acme.settings import Settings, get_settings
import fake_llm

REAL_BUILD_MODEL = factory._build_model


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "grok")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.chdir(tmp_path)  # no stray .env; acme.db lands in tmp_path
    fake_llm.install(monkeypatch)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def real_models(monkeypatch):
    """Build the real provider classes (no call is made) instead of the fake."""
    monkeypatch.setattr(factory, "_build_model", REAL_BUILD_MODEL)


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "acme.db")
    init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def seeded_db(db):
    """`db` with the reference inventory, item aliases, and vendors."""
    seed(db)
    return db
