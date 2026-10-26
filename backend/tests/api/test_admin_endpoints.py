"""Admin settings endpoints (add-admin-payment-settings 4.1): `GET` / `PUT /api/admin/settings`."""

import json

import pytest

from acme.settings import get_settings
from api_helpers import open_client, upload, wait_idle

DEFAULTS = {"delay_payments": True, "pay_at_end_of_day": False, "end_of_day_time": "17:00",
            "end_of_day_timezone": "America/Chicago", "pay_when_queue_empty": True}


def put(client, by="Dana", **change):
    return client.put("/api/admin/settings", json=DEFAULTS | change | {"updated_by": by})


def audit_entries(conn):
    return [json.loads(r["payload_json"]) for r in conn.execute(
        "SELECT payload_json FROM audit_log WHERE event = 'settings.updated' ORDER BY id")]


def test_defaults(client):
    assert client.get("/api/admin/settings").json() == DEFAULTS | {"updated_by": None, "updated_at": None}


def test_turn_on_end_of_day_then_get(client):
    response = put(client, pay_at_end_of_day=True)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved == DEFAULTS | {"pay_at_end_of_day": True, "updated_by": "Dana", "updated_at": saved["updated_at"]}
    assert client.get("/api/admin/settings").json() == saved
    queue = client.get("/api/payment-queue").json()
    assert queue["next_batch_label"].endswith("5:00 PM CT") and queue["pay_at_end_of_day"] is True


def test_name_is_trimmed(client):
    assert put(client, by="  Sam Ortiz  ").json()["updated_by"] == "Sam Ortiz"


@pytest.mark.parametrize("change, by, field", [
    ({"end_of_day_timezone": "Mars/Olympus"}, "Dana", "end_of_day_timezone"),
    ({"end_of_day_time": "25:00"}, "Dana", "end_of_day_time"),
    ({"end_of_day_time": "5pm"}, "Dana", "end_of_day_time"),
    ({}, "   ", "updated_by"),
    ({}, "x" * 51, "updated_by"),
])
def test_invalid_put_is_422_and_saves_nothing(client, conn, change, by, field):
    response = put(client, by=by, pay_at_end_of_day=True, **change)
    assert response.status_code == 422
    assert [d["loc"] for d in response.json()["detail"]] == [["body", field]]
    assert client.get("/api/admin/settings").json()["updated_by"] is None
    assert conn.execute("SELECT COUNT(*) FROM admin_settings").fetchone()[0] == 0 and audit_entries(conn) == []


def test_missing_setting_is_422(client):
    body = {k: v for k, v in DEFAULTS.items() if k != "delay_payments"} | {"updated_by": "Dana"}
    assert client.put("/api/admin/settings", json=body).status_code == 422


def test_audit_entry(client, conn):
    put(client, pay_at_end_of_day=True)
    put(client, pay_at_end_of_day=True, end_of_day_time="15:00")
    assert audit_entries(conn)[-1] == {"by": "Dana", "changes": {"end_of_day_time": ["17:00", "15:00"]}}


def test_endpoints_work_without_an_llm_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    get_settings.cache_clear()
    with open_client() as client:
        assert client.get("/api/stats").json()["llm"]["configured"] is False
        assert client.get("/api/admin/settings").status_code == 200
        response = put(client, delay_payments=False)
        assert response.status_code == 200 and response.json()["delay_payments"] is False


def test_turning_delay_off_pays_the_queue_on_the_runner(client, conn):
    upload(client, "invoice_1001.txt", "invoice_1006.csv")
    assert client.get("/api/payment-queue").json()["count"] == 2
    assert put(client, delay_payments=False).status_code == 200
    wait_idle(client)
    [batch] = client.get("/api/payment-batches").json()["rows"]
    assert (batch["trigger"], batch["released_by"], batch["count"], batch["total_usd"]) == (
        "immediate", "System", 2, "7750.00")
    assert client.get("/api/payment-queue").json()["rows"] == []
    assert put(client, delay_payments=True).status_code == 200  # back on: nothing more is paid
    wait_idle(client)
    assert len(client.get("/api/payment-batches").json()["rows"]) == 1
