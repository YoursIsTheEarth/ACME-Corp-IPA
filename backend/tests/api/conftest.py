"""API test fixtures: an httpx-backed TestClient on a temp `acme.db`, fake model, scheduler off by default."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from acme.db import connect
from acme.payments import mock_bank
from acme.settings import get_settings
import fake_llm
from api_helpers import INVOICES, open_client, pay, upload


@pytest.fixture(autouse=True)
def _api_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "acme.db"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    mock_bank.reset()
    yield
    mock_bank.reset()
    get_settings.cache_clear()


@pytest.fixture
def bank(monkeypatch):
    """Records every `mock_payment` call (the real function still runs, failure hook included)."""
    calls = []
    real = mock_bank.mock_payment

    def recording(vendor, amount):
        calls.append((vendor, amount))
        return real(vendor, amount)

    monkeypatch.setattr(mock_bank, "mock_payment", recording)
    return calls


@pytest.fixture
def client() -> Iterator[TestClient]:
    with open_client() as c:
        yield c


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "acme.db")
    yield c
    c.close()


@pytest.fixture(scope="session")
def api_golden(tmp_path_factory):
    """All 26 golden files uploaded in sorted order through the API, then Pay all. Returns plain data."""
    workdir = tmp_path_factory.mktemp("api_golden")
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(workdir)
        for name, value in (("LLM_PROVIDER", "grok"), ("XAI_API_KEY", "test-key"), ("DB_PATH", str(workdir / "acme.db")),
                            ("UPLOAD_DIR", str(workdir / "uploads"))):
            mp.setenv(name, value)
        get_settings.cache_clear()
        fake_llm.install(mp)
        mock_bank.reset()
        try:
            with open_client() as client:
                names = sorted(p.name for p in INVOICES.iterdir())
                ids = upload(client, *names)
                before = {r["id"]: r for r in client.get("/api/invoices?view=audit").json()["rows"]}
                review = client.get("/api/invoices?view=review").json()["rows"]
                queue = client.get("/api/payment-queue").json()
                batch = pay(client, "Dana")
                conn = connect()
                try:
                    runs = {r["file_name"]: dict(r) for r in conn.execute("SELECT * FROM invoice_runs")}
                finally:
                    conn.close()
                data = {
                    "names": names, "ids": dict(zip(names, ids)), "runs": runs, "before": before, "review": review,
                    "queue": queue, "batch": batch,
                    "batches": client.get("/api/payment-batches").json(),
                    "payments": client.get("/api/payments").json(),
                    "stats": client.get("/api/stats").json(),
                    "detail_1009": client.get(f"/api/invoices/{dict(zip(names, ids))['invoice_1009.json']}").json(),
                }
        finally:
            get_settings.cache_clear()
    return data
