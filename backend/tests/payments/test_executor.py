import threading
from decimal import Decimal

import pytest

from acme.logging import read_trace
from acme.payments import (BatchAlreadyRunning, InvalidBatchRequest, is_batch_running, mock_bank,
                           recover_interrupted_batch, resume_payment_failure, review_hold, run_batch,
                           supersede_original, queue_payment, record_processed)
from acme.payments._store import BATCH_LOCK
from acme.models import Outcome
from acme.settings import get_settings
from golden_invoices import EXPECTED_OUTCOME, GOLDEN_FILES
from payment_helpers import APPROVE, approve, make_run, queue_rows, revised, run_row


def payments(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM payments ORDER BY id")]


class Gate:
    """Replaces `mock_payment` so a test can hold a batch mid-payment."""

    def __init__(self, monkeypatch, bank, on_pay=None):
        self.started, self.release = threading.Event(), threading.Event()
        self.on_pay = on_pay
        recording = mock_bank.mock_payment

        def gated(vendor, amount):
            self.started.set()
            assert self.release.wait(10)
            if self.on_pay:
                self.on_pay(vendor, amount)
            return recording(vendor, amount)
        monkeypatch.setattr(mock_bank, "mock_payment", gated)


def in_thread(fn, *args, **kwargs):
    box = {}

    def target():
        try:
            box["result"] = fn(*args, **kwargs)
        except BaseException as exc:  # surfaced by the test
            box["error"] = exc
    thread = threading.Thread(target=target)
    thread.start()
    return thread, box


# --- 4.1 lock, selection, paying -----------------------------------------------------------

def test_concurrent_pay_all_refused_and_each_row_paid_once(pdb, golden, bank, monkeypatch):
    approve(pdb, "r-1001", golden["invoice_1001.txt"])
    approve(pdb, "r-1006", golden["invoice_1006.csv"])
    gate = Gate(monkeypatch, bank)
    thread, box = in_thread(run_batch, "pay_all", "Dana")
    assert gate.started.wait(5)
    assert is_batch_running()
    assert {r["status"] for r in queue_rows(pdb)} == {"paying"}
    for _ in range(2):
        with pytest.raises(BatchAlreadyRunning):
            run_batch("pay_all", "Lee")
    gate.release.set()
    thread.join(10)
    assert box["result"].count == 2 and "error" not in box
    assert sorted(v for v, _ in bank) == ["Acme Industrial Supplies", "Widgets Inc."]
    assert len(payments(pdb)) == 2 and pdb.execute("SELECT COUNT(*) FROM payment_batches").fetchone()[0] == 1
    assert not is_batch_running()


def test_pay_selected_pays_only_given_rows(pdb, golden, bank):
    ids = [approve(pdb, f"r-{n}", golden[n]).row_id
           for n in ("invoice_1001.txt", "invoice_1006.csv", "invoice_1015.csv")]
    result = run_batch("pay_selected", "Dana", ids=[ids[0], ids[2], 999])
    assert result.count == 2 and len(bank) == 2
    assert [r["status"] for r in queue_rows(pdb)] == ["paid", "queued", "paid"]
    assert [(r.row_id, r.status) for r in result.results if r.status == "skipped"] == [(999, "skipped")]


def test_pay_now_one_row(pdb, golden):
    row_id = approve(pdb, "r-1001", golden["invoice_1001.txt"]).row_id
    approve(pdb, "r-1006", golden["invoice_1006.csv"])
    assert run_batch("pay_now", "Dana", ids=[row_id]).count == 1
    assert [r["status"] for r in queue_rows(pdb)] == ["paid", "queued"]


def test_scoped_trigger_needs_ids(pdb):
    with pytest.raises(InvalidBatchRequest):
        run_batch("pay_selected", "Dana")


# --- 4.2 re-check, ledger, paid -------------------------------------------------------------

def test_batch_pays_and_records_ledger(pdb, golden, bank):
    approve(pdb, "r-1001", golden["invoice_1001.txt"])
    result = run_batch("pay_all", "Dana")
    [payment] = payments(pdb)
    assert (payment["idempotency_key"], payment["amount_usd"], payment["batch_id"]) == (
        "widgets inc.|INV-1001|0", "5000.00", result.batch_id)
    assert payment["payment_id"] == "PAY-000001" and payment["paid_at"]
    assert bank == [("Widgets Inc.", Decimal("5000.00"))]
    run = run_row(pdb, "r-1001")
    assert (run["final_status"], run["status"]) == ("Paid", "Resolved")
    assert queue_rows(pdb)[0]["status"] == "paid"
    assert [e["event"] for e in read_trace("r-1001", pdb)][-1] == "payment.created"


def test_second_batch_makes_zero_payments(pdb, golden, bank):
    approve(pdb, "r-1001", golden["invoice_1001.txt"])
    run_batch("pay_all", "Dana")
    again = run_batch("pay_all", "Dana")
    assert (again.count, again.total_usd, len(bank), len(payments(pdb))) == (0, Decimal("0.00"), 1, 1)


def test_row_cancelled_mid_batch_is_skipped(pdb, golden, bank, monkeypatch):
    approve(pdb, "r-1001", golden["invoice_1001.txt"])
    second = approve(pdb, "r-1006", golden["invoice_1006.csv"]).row_id

    def cancel_second(vendor, amount):
        from acme.db import connect
        other = connect()
        other.execute("UPDATE payment_queue SET status = 'cancelled' WHERE id = ?", (second,))
        other.commit()
        other.close()
    gate = Gate(monkeypatch, bank, on_pay=cancel_second)
    gate.release.set()
    result = run_batch("pay_all", "Dana")
    assert [v for v, _ in bank] == ["Widgets Inc."]
    assert [(r.status, r.error) for r in result.results][1] == ("skipped", "row is cancelled")
    assert result.count == 1


def test_superseded_run_is_skipped(pdb, golden, bank):
    approve(pdb, "r-1001", golden["invoice_1001.txt"])
    pdb.execute("UPDATE invoice_runs SET final_status = 'Superseded'")
    pdb.commit()
    assert run_batch("pay_all", "Dana").count == 0 and bank == []
    assert queue_rows(pdb)[0]["status"] == "cancelled"


def test_used_idempotency_key_is_marked_paid_without_paying(pdb, golden, bank):
    approve(pdb, "r-1001", golden["invoice_1001.txt"])
    pdb.execute("INSERT INTO payments (idempotency_key, vendor, amount_usd, paid_at) "
                "VALUES ('widgets inc.|INV-1001|0', 'Widgets Inc.', '5000.00', 'x')")
    pdb.commit()
    result = run_batch("pay_all", "Dana")
    assert bank == [] and result.count == 0
    assert (result.results[0].status, result.results[0].error) == ("already_paid", "already paid")
    assert queue_rows(pdb)[0]["status"] == "paid" and run_row(pdb, "r-1001")["final_status"] == "Paid"


# --- 4.3 failures ----------------------------------------------------------------------------

def test_failure_is_retried_then_escalated_after_three(pdb, golden, bank):
    approve(pdb, "r-1001", golden["invoice_1001.txt"])
    for attempt in (1, 2):
        mock_bank.fail_next(1, "bank timeout")
        result = run_batch("pay_all", "Dana")
        assert (result.failed_count, result.results[0].status) == (1, "failed")
        row = queue_rows(pdb)[0]
        assert (row["status"], row["attempts"]) == ("failed", attempt)
        assert row["last_error"] == "PaymentError: bank timeout"
    mock_bank.fail_next(1, "bank down")
    assert run_batch("pay_all", "Dana").results[0].status == "escalated"
    row = queue_rows(pdb)[0]
    assert (row["status"], row["attempts"], row["last_error"]) == ("cancelled", 3, "PaymentError: bank down")
    assert run_row(pdb, "r-1001")["status"] == "Awaiting review"
    hold = review_hold("r-1001")
    assert hold.kind == "payment_failure" and hold.reason == "payment failed 3 times: PaymentError: bank down"
    assert run_batch("pay_all", "Dana").results == [] and len(bank) == 3 and payments(pdb) == []


def test_non_success_status_is_a_failure(pdb, golden, monkeypatch):
    approve(pdb, "r-1001", golden["invoice_1001.txt"])
    monkeypatch.setattr(mock_bank, "mock_payment", lambda vendor, amount: {"status": "declined"})
    assert run_batch("pay_all", "Dana").failed_count == 1
    assert queue_rows(pdb)[0]["status"] == "failed" and payments(pdb) == []


# --- 4.4 batch records -----------------------------------------------------------------------

def golden_disposition(conn, golden):
    for name in GOLDEN_FILES:
        if EXPECTED_OUTCOME[name] != "APPROVE":
            continue
        invoice = golden[name]
        make_run(conn, name)
        record_processed(name, invoice, Outcome.APPROVE)
        if invoice.revision:
            supersede_original(invoice, name)
        queue_payment(name, invoice, APPROVE)


def test_pay_all_after_golden_run_records_the_batch(pdb, golden, bank):
    golden_disposition(pdb, golden)
    result = run_batch("pay_all", "  Dana ")
    assert (result.count, result.total_usd, result.failed_count, result.released_by) == (
        7, Decimal("37620.00"), 0, "Dana")
    batch = dict(pdb.execute("SELECT * FROM payment_batches").fetchone())
    assert (batch["batch_id"], batch["trigger"], batch["released_by"], batch["count"], batch["total_usd"],
            batch["failed_count"]) == (result.batch_id, "pay_all", "Dana", 7, "37620.00", 0)
    assert batch["started_at"] and batch["finished_at"]
    assert run_row(pdb, "invoice_1004.json")["final_status"] == "Superseded"
    assert ("Precision Parts Ltd.", Decimal("5940.00")) in bank and len(bank) == 7
    [finished] = [e for e in read_trace_all(pdb) if e["event"] == "batch.finished"]
    assert len(finished["payload"]["results"]) == 7


def read_trace_all(conn):
    import json
    return [{"event": r["event"], "payload": json.loads(r["payload_json"])}
            for r in conn.execute("SELECT event, payload_json FROM audit_log WHERE run_id IS NULL ORDER BY id")]


@pytest.mark.parametrize("name", ["", "   ", None, "x" * 51])
def test_bad_release_name_is_refused(pdb, golden, name, bank):
    approve(pdb, "r-1001", golden["invoice_1001.txt"])
    with pytest.raises(InvalidBatchRequest):
        run_batch("pay_all", name)
    assert pdb.execute("SELECT COUNT(*) FROM payment_batches").fetchone()[0] == 0 and bank == []


def test_fifty_chars_ok_and_system_for_scheduled_triggers(pdb):
    assert run_batch("pay_all", "x" * 50).released_by == "x" * 50
    assert run_batch("end_of_day").released_by == "System"
    assert run_batch("idle", "Dana").released_by == "System"
    assert [r["batch_id"] for r in pdb.execute("SELECT batch_id FROM payment_batches ORDER BY batch_id")] == [
        "B-0001", "B-0002", "B-0003"]


def test_unknown_trigger_refused(pdb):
    with pytest.raises(InvalidBatchRequest):
        run_batch("cli", "Dana")


# --- 4.5 recovery ----------------------------------------------------------------------------

def test_crash_mid_batch_recovery(pdb, golden, bank):
    for name in ("invoice_1001.txt", "invoice_1006.csv", "invoice_1015.csv"):
        approve(pdb, name, golden[name])
    pdb.execute("INSERT INTO payment_batches (batch_id, trigger, released_by, started_at) "
                "VALUES ('B-0001', 'pay_all', 'Dana', 'x')")
    pdb.execute("UPDATE payment_queue SET status = 'paying', batch_id = 'B-0001'")
    pdb.execute("INSERT INTO payments (idempotency_key, vendor, amount_usd, paid_at, batch_id) "
                "VALUES ('widgets inc.|INV-1001|0', 'Widgets Inc.', '5000.00', 'x', 'B-0001')")
    pdb.commit()
    assert recover_interrupted_batch() == {"paid": 1, "requeued": 2}
    rows = queue_rows(pdb)
    assert [(r["status"], r["attempts"], r["last_error"]) for r in rows] == [
        ("paid", 0, None), ("queued", 0, "interrupted"), ("queued", 0, "interrupted")]
    assert run_row(pdb, "invoice_1001.txt")["final_status"] == "Paid"
    batch = pdb.execute("SELECT finished_at, count, total_usd FROM payment_batches").fetchone()
    assert batch["finished_at"] and (batch["count"], batch["total_usd"]) == (1, "5000.00")
    result = run_batch("pay_all", "Dana")
    assert result.count == 2 and len(bank) == 2 and len(payments(pdb)) == 3


# --- 4.7 payment-failure decisions -----------------------------------------------------------

def escalate(conn, golden, bank):
    approve(conn, "r-1001", golden["invoice_1001.txt"])
    for _ in range(get_settings().payment_max_attempts):
        mock_bank.fail_next(1, "bank down")
        run_batch("pay_all", "Dana")
    bank.clear()


def test_approve_payment_failure_requeues(pdb, golden, bank):
    escalate(pdb, golden, bank)
    new_id = resume_payment_failure("r-1001", approve=True, reviewer="Dana", rationale="Bank is back up now.")
    row = queue_rows(pdb)[-1]
    assert (row["id"], row["status"], row["attempts"], row["kind"], row["amount_usd"]) == (
        new_id, "queued", 0, "full", "5000.00")
    assert run_batch("pay_all", "Dana").count == 1 and len(bank) == 1
    assert payments(pdb)[0]["idempotency_key"] == "widgets inc.|INV-1001|0"
    assert run_row(pdb, "r-1001")["final_status"] == "Paid"


def test_reject_payment_failure_closes_it(pdb, golden, bank):
    escalate(pdb, golden, bank)
    assert resume_payment_failure("r-1001", approve=False, reviewer="Dana", rationale="Vendor bank closed.") is None
    run = run_row(pdb, "r-1001")
    assert (run["final_status"], run["decided_by"]) == ("Rejected", "Dana")
    [event] = [e for e in read_trace("r-1001", pdb) if e["event"] == "rejection.recorded"]
    assert event["payload"]["last_error"] == "PaymentError: bank down"
    assert event["payload"]["rationale"] == "Vendor bank closed."
    assert run_batch("pay_all", "Dana").results == [] and bank == []


def test_resume_without_hold_fails(pdb, golden):
    approve(pdb, "r-1001", golden["invoice_1001.txt"])
    with pytest.raises(ValueError):
        resume_payment_failure("r-1001", approve=True)


# --- 4.6 WAIT_FOR_PAYMENT ----------------------------------------------------------------------

def disposition(invoice, run_id):
    record_processed(run_id, invoice, Outcome.APPROVE)
    supersede_original(invoice, run_id)
    return queue_payment(run_id, invoice, APPROVE)


@pytest.mark.parametrize("fails, expected", [(False, ("delta", Decimal("500.00"))),
                                             (True, ("replacement", Decimal("2390.00")))])
def test_revision_mid_batch_waits_for_the_payment(pdb, golden, bank, monkeypatch, fails, expected):
    approve(pdb, "r-1004", golden["invoice_1004.json"])
    make_run(pdb, "r-1004r")
    gate = Gate(monkeypatch, bank)
    if fails:
        mock_bank.fail_next(1, "bank down")
    batch, _ = in_thread(run_batch, "pay_all", "Dana")
    assert gate.started.wait(5)
    worker, box = in_thread(disposition, revised(golden["invoice_1004.json"], "2390.00"), "r-1004r")
    worker.join(0.3)
    assert worker.is_alive()  # waiting on the batch lock
    gate.release.set()
    batch.join(10)
    worker.join(10)
    assert (box["result"].kind, box["result"].amount) == expected
    assert run_row(pdb, "r-1004")["final_status"] == ("Superseded" if fails else "Paid")


def test_revision_lock_timeout_falls_back_to_review(pdb, golden, monkeypatch):
    monkeypatch.setenv("PAYMENT_LOCK_TIMEOUT_S", "0")
    get_settings.cache_clear()
    approve(pdb, "r-1004", golden["invoice_1004.json"])
    make_run(pdb, "r-1004r")
    pdb.execute("UPDATE payment_queue SET status = 'paying'")
    pdb.commit()
    with BATCH_LOCK:
        result = disposition(revised(golden["invoice_1004.json"], "2390.00"), "r-1004r")
    assert result.action == "held" and review_hold("r-1004r").kind == "warning"
    assert run_row(pdb, "r-1004r")["status"] == "Awaiting review"
    assert [r["run_id"] for r in queue_rows(pdb)] == ["r-1004"]
