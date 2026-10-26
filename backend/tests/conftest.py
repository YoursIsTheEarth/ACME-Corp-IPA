"""Every test runs in an empty temp directory with a dummy Grok key and the test-only fake model.

No test reaches a provider API: `acme.llm.factory._build_model` returns `fake_llm.FakeChatModel`.
Tests of the missing-key path delete `XAI_API_KEY`; tests of the real model classes use `real_models`.
"""

from contextlib import contextmanager

import pytest

from acme.admin import PaymentTiming, save_payment_timing
from acme.db import connect, init_schema
from acme.db.seed import seed
from acme.llm import factory
from acme.payments import mock_bank
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


@pytest.fixture(scope="session")
def run_golden(tmp_path_factory):
    """`with run_golden(timing) as (conn, calls):` a fresh seeded `acme.db` in its own directory with the fake
    model, a dummy Grok key, `timing` saved with `save_payment_timing`, and every `mock_payment` call recorded.

    The golden suite runs in two configurations: the default timing and delay off (immediate payments).
    """
    @contextmanager
    def run(timing: PaymentTiming):
        workdir = tmp_path_factory.mktemp("golden")
        with pytest.MonkeyPatch.context() as mp:
            mp.chdir(workdir)
            mp.setenv("LLM_PROVIDER", "grok")
            mp.setenv("XAI_API_KEY", "test-key")
            mp.setenv("DB_PATH", str(workdir / "acme.db"))
            calls = []
            real_payment = mock_bank.mock_payment
            mp.setattr(mock_bank, "mock_payment", lambda vendor, amount: calls.append((vendor, amount))
                       or real_payment(vendor, amount))
            mock_bank.reset()
            get_settings.cache_clear()
            fake_llm.install(mp)
            conn = connect()
            try:
                seed(conn)
                save_payment_timing(timing, "golden", conn)
                yield conn, calls
            finally:
                conn.close()
                get_settings.cache_clear()
    return run
