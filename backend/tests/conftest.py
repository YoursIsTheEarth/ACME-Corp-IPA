"""Every test runs offline, with no API keys, in an empty temp directory."""

import pytest

from acme.db import connect, init_schema
from acme.db.seed import seed
from acme.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "offline")
    monkeypatch.chdir(tmp_path)  # no stray .env; acme.db lands in tmp_path
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
