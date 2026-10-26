"""Running without an LLM key (tasks 5.1-5.3): the API starts, reports the key status, refuses uploads
with 503, keeps review and payment working, and leaves pending runs for a restart with a key."""

import pytest

from acme.llm import ProviderConfigError
from acme.settings import get_settings
from acme.workflow import create_run
from api_helpers import file_part, open_client, pay, upload, wait_idle

MESSAGE = ("No LLM token provided: set XAI_API_KEY for Grok (in .env or the environment). "
           "The app cannot process invoices without it.")
RATIONALE = "Rush pricing agreed by procurement"


def _set_key(monkeypatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("XAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("XAI_API_KEY", value)
    get_settings.cache_clear()


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_starts_and_reports_missing_key(monkeypatch):
    _set_key(monkeypatch, None)
    with open_client() as client:
        stats = client.get("/api/stats").json()
        assert (stats["llm"]["configured"], stats["llm"]["missing_key"]) == (False, "XAI_API_KEY")
        assert stats["llm"]["provider"] == "grok"
        assert client.get("/api/invoices?view=queue").status_code == 200


def test_invalid_provider_still_stops_startup(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "offline")
    get_settings.cache_clear()
    with pytest.raises(ProviderConfigError, match="valid values are: grok, claude"):
        with open_client():
            pass


def test_upload_refused_with_503(monkeypatch, conn, tmp_path):
    _set_key(monkeypatch, None)
    with open_client() as client:
        response = client.post("/api/invoices", files=[file_part("invoice_1001.txt")])
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "llm_not_configured", "message": MESSAGE,
                                          "missing_key": "XAI_API_KEY"}}
    assert _count(conn, "invoice_runs") == 0
    uploads = tmp_path / "uploads"
    assert not uploads.exists() or not any(p.is_file() for p in uploads.rglob("*"))


def test_review_and_payment_work_without_a_key(monkeypatch):
    with open_client() as client:
        [held] = upload(client, "invoice_1010.txt")
        [queued] = upload(client, "invoice_1001.txt")
    _set_key(monkeypatch, None)
    with open_client() as client:
        response = client.post(f"/api/invoices/{held}/review",
                               json={"decision": "approve", "reviewer": "Dana", "rationale": RATIONALE})
        assert response.status_code == 200
        wait_idle(client)
        assert {r["run_id"] for r in client.get("/api/payment-queue").json()["rows"]} == {held, queued}
        pay(client)
        assert {p["run_id"] for p in client.get("/api/payments").json()["rows"]} == {held, queued}


def test_pending_run_waits_for_a_key(monkeypatch, conn):
    with open_client():
        pass  # create and seed the db
    pending = create_run("invoice_1002.txt")
    stuck = create_run("invoice_1007.csv")
    conn.execute("UPDATE invoice_runs SET stage = 'Validating', status = 'Processing' WHERE id = ?", (stuck,))
    conn.commit()
    _set_key(monkeypatch, None)
    with open_client() as client:
        wait_idle(client)
        rows = {r["id"]: r for r in client.get("/api/invoices?view=queue").json()["rows"]}
        assert {rows[pending]["stage"], rows[stuck]["stage"]} == {"Uploaded"}
    assert {tuple(r) for r in conn.execute("SELECT stage, status FROM invoice_runs")} == {("Uploaded", "Uploaded")}
    assert _count(conn, "llm_calls") == 0
    _set_key(monkeypatch, "test-key")
    with open_client() as client:
        wait_idle(client)
        audit = {r["id"]: r for r in client.get("/api/invoices?view=audit").json()["rows"]}
        assert audit[pending]["final_status"] == audit[stuck]["final_status"] == "Rejected"
