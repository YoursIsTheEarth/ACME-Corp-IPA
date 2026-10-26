"""Batch execution and the scheduler (tasks 5.1, 5.2)."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from acme import workflow
from acme.admin import PaymentTiming, save_payment_timing
from acme.payments import mock_bank
from acme.payments._store import BATCH_LOCK
from acme.settings import get_settings
from api_helpers import open_client, pay, upload, wait_idle

THREE = ("invoice_1001.txt", "invoice_1006.csv", "invoice_1015.csv")


def queue_rows(client):
    return client.get("/api/payment-queue").json()["rows"]


def batch_record(conn, batch_id):
    return dict(conn.execute("SELECT * FROM payment_batches WHERE batch_id = ?", (batch_id,)).fetchone())


# --- 5.1 ---------------------------------------------------------------------------------------

def test_pay_all(client, conn, bank):
    upload(client, *THREE)
    body = pay(client, "Dana")
    assert body["trigger"] == "pay_all" and body["batch_id"].startswith("B-")
    record = batch_record(conn, body["batch_id"])
    assert (record["trigger"], record["released_by"], record["count"]) == ("pay_all", "Dana", 3)
    assert queue_rows(client) == [] and len(bank) == 3


def test_pay_selected_pays_only_those_rows(client, conn):
    upload(client, *THREE, "invoice_1011.pdf", "invoice_1012.pdf")
    rows = queue_rows(client)
    assert len(rows) == 5
    chosen = [rows[0]["id"], rows[2]["id"]]
    body = pay(client, "Sam Ortiz", ids=chosen)
    assert body["trigger"] == "pay_selected"
    assert batch_record(conn, body["batch_id"])["count"] == 2
    left = queue_rows(client)
    assert len(left) == 3 and not {r["id"] for r in left} & set(chosen)
    assert all(r["status"] == "queued" for r in left)


def test_pay_now_pays_one_row(client, conn):
    upload(client, *THREE)
    row = queue_rows(client)[1]
    body = pay(client, "Dana", ids=[row["id"]])
    assert body["trigger"] == "pay_now" and batch_record(conn, body["batch_id"])["count"] == 1
    assert row["id"] not in {r["id"] for r in queue_rows(client)}


def test_skipped_ids_are_reported(client, conn):
    upload(client, "invoice_1001.txt")
    body = pay(client, "Dana", ids=[999, queue_rows(client)[0]["id"]])
    assert batch_record(conn, body["batch_id"])["count"] == 1
    finished = conn.execute("SELECT payload_json FROM audit_log WHERE event = 'batch.finished'").fetchone()[0]
    assert "row_id=999, status='skipped'" in finished  # RowResult is stored as its repr


@pytest.mark.parametrize("body", [{"released_by": ""}, {"released_by": "   "}, {"released_by": "x" * 51}, {},
                                  {"released_by": "Dana", "ids": []}])
def test_invalid_execute_is_422(client, conn, body):
    upload(client, "invoice_1001.txt")
    assert client.post("/api/payment-queue/execute", json=body).status_code == 422
    assert conn.execute("SELECT COUNT(*) FROM payment_batches").fetchone()[0] == 0


def test_concurrent_pay_all_gives_409(client, conn, monkeypatch):
    upload(client, *THREE)
    release, calls = threading.Event(), []
    real = mock_bank.mock_payment

    def slow(vendor, amount):
        calls.append(vendor)
        release.wait(10)
        return real(vendor, amount)

    monkeypatch.setattr(mock_bank, "mock_payment", slow)
    first = client.post("/api/payment-queue/execute", json={"released_by": "Dana"})
    assert first.status_code == 202
    with ThreadPoolExecutor(2) as pool:
        others = list(pool.map(lambda name: client.post("/api/payment-queue/execute", json={"released_by": name}),
                               ["Sam", "Lee"]))
    assert [r.status_code for r in others] == [409, 409]
    assert client.get("/api/payment-queue").json()["batch_running"] is True
    release.set()
    wait_idle(client)
    assert conn.execute("SELECT COUNT(*) FROM payment_batches").fetchone()[0] == 1
    assert len(calls) == 3 and conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 3
    assert queue_rows(client) == []


# --- 5.2 ---------------------------------------------------------------------------------------

def tick(client, now, wait=True):
    svc = client.app.state.services
    batch_id = client.portal.call(svc.scheduler.idle_tick, now)
    if wait:
        wait_idle(client)
    return batch_id


def last_activity(conn) -> datetime:
    return datetime.fromisoformat(conn.execute("SELECT MAX(ts) FROM audit_log").fetchone()[0])


@pytest.fixture
def end_of_day_on(db):
    save_payment_timing(PaymentTiming(pay_at_end_of_day=True), "Dana")  # delay on, 17:00 America/Chicago


# Idle tests run with the default timing: delay on, pay when the Invoice Queue is empty on.

def test_idle_waits_for_whole_upload(client, conn, monkeypatch):
    gate, real = threading.Event(), workflow.process_run

    def gated(*args, **kwargs):
        gate.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr(workflow, "process_run", gated)
    upload(client, *THREE, wait=False)
    assert tick(client, datetime.now(timezone.utc) + timedelta(hours=1), wait=False) is None  # all 3 still Uploaded
    gate.set()
    wait_idle(client)
    assert len(queue_rows(client)) == 3
    last = last_activity(conn)
    assert tick(client, last + timedelta(seconds=30)) is None
    batch_id = tick(client, last + timedelta(seconds=61))
    record = batch_record(conn, batch_id)
    assert (record["trigger"], record["released_by"], record["count"]) == ("idle", "System", 3)
    assert queue_rows(client) == []
    assert tick(client, last + timedelta(hours=1)) is None  # nothing left to pay


def test_idle_blocked_while_processing(client, conn):
    upload(client, "invoice_1001.txt")
    conn.execute("INSERT INTO invoice_runs (id, file_name, uploaded_at, status, stage) "
                 "VALUES ('run-busy', 'x.txt', ?, 'Processing', 'Validating')", (datetime.now(timezone.utc).isoformat(),))
    conn.commit()
    assert tick(client, datetime.now(timezone.utc) + timedelta(hours=1)) is None
    conn.execute("UPDATE invoice_runs SET stage = 'Resolved', status = 'Resolved' WHERE id = 'run-busy'")
    conn.commit()
    assert tick(client, datetime.now(timezone.utc) + timedelta(hours=1)) is not None


def test_held_invoice_does_not_block_idle(client, conn):
    upload(client, "invoice_1001.txt", "invoice_1010.txt")
    assert client.get("/api/stats").json()["awaiting_review"] == 1
    batch_id = tick(client, last_activity(conn) + timedelta(seconds=61))
    assert batch_record(conn, batch_id)["count"] == 1


def test_idle_disabled(client, conn):
    save_payment_timing(PaymentTiming(pay_when_queue_empty=False), "Dana")
    upload(client, "invoice_1001.txt")
    assert tick(client, datetime.now(timezone.utc) + timedelta(days=1)) is None
    assert client.get("/api/payment-queue").json()["pay_when_queue_empty"] is False
    assert conn.execute("SELECT COUNT(*) FROM payment_batches").fetchone()[0] == 0


def test_scheduled_ticks_skip_while_a_batch_runs(end_of_day_on, client, conn):
    upload(client, "invoice_1001.txt")
    svc = client.app.state.services
    with BATCH_LOCK:
        assert tick(client, datetime.now(timezone.utc) + timedelta(hours=1)) is None
        assert client.portal.call(svc.scheduler.end_of_day) is None
    assert conn.execute("SELECT COUNT(*) FROM payment_batches").fetchone()[0] == 0
    batch_id = client.portal.call(svc.scheduler.end_of_day)
    wait_idle(client)
    record = batch_record(conn, batch_id)
    assert (record["trigger"], record["released_by"], record["count"]) == ("end_of_day", "System", 1)


def test_end_of_day_job_does_nothing_when_turned_off(client, conn):
    upload(client, "invoice_1001.txt")
    assert client.portal.call(client.app.state.services.scheduler.end_of_day) is None  # defaults: end of day off
    assert conn.execute("SELECT COUNT(*) FROM payment_batches").fetchone()[0] == 0


def eod_local(scheduler):
    job = scheduler.get_job("end_of_day")
    return None if job is None else job.next_run_time.astimezone(ZoneInfo("America/Chicago"))


def test_scheduler_jobs(end_of_day_on):
    with open_client(enable_scheduler=True) as client:
        scheduler = client.app.state.services.scheduler.scheduler
        local = eod_local(scheduler)
        assert (local.hour, local.minute) == (17, 0)
        assert scheduler.get_job("idle_check").trigger.interval == timedelta(seconds=5)


def test_defaults_schedule_no_end_of_day_job():
    with open_client(enable_scheduler=True) as client:
        scheduler = client.app.state.services.scheduler.scheduler
        assert scheduler.get_job("end_of_day") is None and scheduler.get_job("idle_check") is not None


def test_saving_settings_reschedules_without_restart(end_of_day_on):
    body = {"delay_payments": True, "pay_at_end_of_day": True, "end_of_day_time": "15:00",
            "end_of_day_timezone": "America/Chicago", "pay_when_queue_empty": True, "updated_by": "Dana"}
    with open_client(enable_scheduler=True) as client:
        scheduler = client.app.state.services.scheduler.scheduler
        assert (eod_local(scheduler).hour, eod_local(scheduler).minute) == (17, 0)
        assert client.put("/api/admin/settings", json=body).status_code == 200
        assert (eod_local(scheduler).hour, eod_local(scheduler).minute) == (15, 0)  # moved, not added
        assert [j.id for j in scheduler.get_jobs()].count("end_of_day") == 1
        assert client.put("/api/admin/settings", json=body | {"pay_at_end_of_day": False}).status_code == 200
        assert scheduler.get_job("end_of_day") is None


def test_tick_picks_up_settings_saved_elsewhere():
    with open_client(enable_scheduler=True) as client:
        svc = client.app.state.services
        assert svc.scheduler.scheduler.get_job("end_of_day") is None
        save_payment_timing(PaymentTiming(pay_at_end_of_day=True, end_of_day_time="08:30"), "cli")  # like `admin set`
        client.portal.call(svc.scheduler.idle_tick)
        assert (eod_local(svc.scheduler.scheduler).hour, eod_local(svc.scheduler.scheduler).minute) == (8, 30)


def test_delay_off_pays_a_stranded_row_within_one_tick(client, conn):
    upload(client, "invoice_1001.txt")
    # Delay turned off elsewhere without paying (e.g. the process died before its immediate batch ran).
    save_payment_timing(PaymentTiming(delay_payments=False), "Dana", pay_queued=False)
    assert len(queue_rows(client)) == 1
    batch_id = tick(client, datetime.now(timezone.utc))
    record = batch_record(conn, batch_id)
    assert (record["trigger"], record["released_by"], record["count"]) == ("immediate", "System", 1)
    assert queue_rows(client) == []
    assert tick(client, datetime.now(timezone.utc)) is None  # nothing payable: no empty batch
