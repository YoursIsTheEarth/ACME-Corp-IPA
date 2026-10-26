"""Payee threshold end to end: the ledger at disposition, retroactive flags, and payee-threshold hold decisions."""

import threading
import time

import pytest

from acme import payments
from acme.admin import PaymentTiming, save_payment_timing
from acme.logging import read_trace
from acme.payments import mock_bank, review_hold, run_batch
from acme.workflow import ReviewConflict, resume_review, run_invoice
from workflow_helpers import INVOICES, queue_rows, run_row

RATIONALE = "Confirmed with procurement: separate purchase orders"


def ledger(conn, run_id):
    return [dict(r) for r in conn.execute("SELECT * FROM payee_invoices WHERE run_id = ? ORDER BY payee_id",
                                          (run_id,))]


def trail(run_id, event):
    return [e["payload"] for e in read_trace(run_id) if e["event"] == event]


def run(name, **kwargs):
    return run_invoice(INVOICES / name, **kwargs)


@pytest.fixture
def cancelled():
    received = []
    unsubscribe = payments.subscribe(lambda name, data: received.append(data) if name == "payment.cancelled" else None)
    yield received
    unsubscribe()


# --- 6.1 ledger --------------------------------------------------------------------------------

def test_every_disposition_is_recorded_in_the_payee_ledger(wdb):
    rejected = run("invoice_1002.txt")
    first, duplicate = run("invoice_1011.pdf"), run("invoice_1011.txt")
    assert [(r["invoice_number"], r["total_usd"], r["outcome"]) for r in ledger(wdb, rejected.run_id)] == [
        ("INV-1002", "15000.00", "Rejected")]
    assert [r["outcome"] for r in ledger(wdb, first.run_id)] == ["Queued for payment"]
    assert [(r["invoice_number"], r["outcome"]) for r in ledger(wdb, duplicate.run_id)] == [("INV-1011", "Duplicate")]
    no_vendor = run("invoice_1009.json")
    assert no_vendor.outcome == "REJECT" and ledger(wdb, no_vendor.run_id) == []


# --- 6.2 retroactive flags -------------------------------------------------------------------

def test_earlier_split_invoice_pulled_into_review(wdb, cancelled):
    first = run("invoice_1018.txt")
    [row] = queue_rows(wdb, first.run_id)
    events = []
    second = run("invoice_1019.json", on_event=lambda name, data: events.append((name, data)))
    assert second.outcome == "NEEDS_REVIEW" and "PAYEE_CUMULATIVE_THRESHOLD" in {f.code.value for f in second.findings}

    assert run_row(wdb, first.run_id)["status"] == "Awaiting review"
    assert [r["status"] for r in queue_rows(wdb, first.run_id)] == ["cancelled"]
    hold = review_hold(first.run_id)
    assert (hold.kind, hold.reason, hold.details["pulled"], hold.details["row_id"]) == (
        "payee_threshold", "Payee cumulative threshold", True, row["id"])
    assert hold.details["findings"] == ["PAYEE_CUMULATIVE_THRESHOLD"]
    threshold = hold.details["payee_threshold"]
    assert threshold["total"] == "19250.00" and threshold["triggered_by"] == second.run_id
    assert [(i["invoice_number"], i["run_id"]) for i in threshold["invoices"]] == [
        ("INV-1018", first.run_id), ("INV-1019", second.run_id)]
    assert cancelled == [{"row_id": row["id"], "run_id": first.run_id, "reason": "payee_threshold"}]
    assert ("invoice.stage_changed", {"run_id": first.run_id, "stage": "Awaiting review",
                                      "status": "Awaiting review"}) in events
    [outcome] = trail(second.run_id, "disposition.outcome")
    assert outcome["pulled"] == [first.run_id]
    assert [r["outcome"] for r in ledger(wdb, first.run_id)] == ["Awaiting review"]
    assert run_batch("pay_all", "test").count == 0


def test_held_invoices_gain_the_latest_total(wdb):
    first, second, third = run("invoice_1018.txt"), run("invoice_1019.json"), run("invoice_1020.csv")
    assert third.outcome == "NEEDS_REVIEW"
    for result in (first, second, third):
        hold = review_hold(result.run_id)
        assert "PAYEE_CUMULATIVE_THRESHOLD" in hold.details["findings"]
        assert hold.details["payee_threshold"]["total"] == "29000.00", result.file
        assert [i["invoice_number"] for i in hold.details["payee_threshold"]["invoices"]] == [
            "INV-1018", "INV-1019", "INV-1020"]
    assert review_hold(first.run_id).kind == "payee_threshold" and review_hold(second.run_id).kind == "warning"
    assert "$29,000.00" in review_hold(second.run_id).reason and "$19,250.00" not in review_hold(second.run_id).reason
    assert run_row(wdb, first.run_id)["status"] == run_row(wdb, second.run_id)["status"] == "Awaiting review"


def test_paid_invoice_flagged_after_the_fact(wdb, bank):
    save_payment_timing(PaymentTiming(delay_payments=False), "test")
    first = run("invoice_1018.txt")
    assert first.final_status == "Paid"
    second = run("invoice_1019.json")
    assert run_row(wdb, first.run_id)["final_status"] == "Paid" and len(bank) == 1  # nothing recalled
    [flag] = trail(first.run_id, "finding.retroactive")
    assert flag["finding"]["code"] == "PAYEE_CUMULATIVE_THRESHOLD" and flag["total"] == "19250.00"
    assert flag["triggered_by"] == {"run_id": second.run_id, "invoice_number": "INV-1019"}
    assert flag["status"] == "Resolved"


def test_row_paying_in_a_running_batch_is_treated_as_paid(wdb, monkeypatch):
    first = run("invoice_1018.txt")
    started, release = threading.Event(), threading.Event()
    real = mock_bank.mock_payment

    def slow(vendor, amount):
        started.set()
        release.wait(10)
        return real(vendor, amount)

    monkeypatch.setattr(mock_bank, "mock_payment", slow)
    batch = threading.Thread(target=run_batch, args=("pay_all", "test"))
    batch.start()
    assert started.wait(10)
    results = []
    worker = threading.Thread(target=lambda: results.append(run("invoice_1019.json")))
    worker.start()
    deadline = time.monotonic() + 10
    while not wdb.execute("SELECT 1 FROM payee_invoices WHERE invoice_number = 'INV-1019'").fetchone():
        assert time.monotonic() < deadline
        time.sleep(0.02)
    time.sleep(0.2)  # disposition is now waiting for the batch lock
    assert [r["status"] for r in queue_rows(wdb, first.run_id)] == ["paying"]
    release.set()
    batch.join(10)
    worker.join(10)
    assert results and results[0].outcome == "NEEDS_REVIEW"
    assert [r["status"] for r in queue_rows(wdb, first.run_id)] == ["paid"]
    assert run_row(wdb, first.run_id)["final_status"] == "Paid"
    assert [f["status"] for f in trail(first.run_id, "finding.retroactive")] == ["Resolved"]


def test_rejected_contributor_is_flagged_and_stays_rejected(wdb, tmp_path):
    text = (INVOICES / "invoice_1018.txt").read_text().replace("qty: 2 ", "qty: 9 ")  # GadgetX over stock
    path = tmp_path / "over.txt"
    path.write_text(text.replace("$9,750.00", "$15,000.00"))
    rejected = run_invoice(path)
    assert rejected.final_status == "Rejected"
    second = run("invoice_1019.json")
    assert second.outcome == "NEEDS_REVIEW"
    assert run_row(wdb, rejected.run_id)["final_status"] == "Rejected"
    [flag] = trail(rejected.run_id, "finding.retroactive")
    assert flag["total"] == "24500.00"


# --- 6.3 hold decisions ----------------------------------------------------------------------

def _pulled(wdb):
    first, second = run("invoice_1018.txt"), run("invoice_1019.json")
    assert review_hold(first.run_id).kind == "payee_threshold"
    return first, second


def test_approve_requeues_and_the_next_batch_pays_once(wdb, bank):
    first, _ = _pulled(wdb)
    [old] = queue_rows(wdb, first.run_id)
    result = resume_review(first.run_id, "approve", "Dana", RATIONALE)
    assert (result.status, result.decided_by) == ("Queued for payment", "Dana")
    cancelled, fresh = queue_rows(wdb, first.run_id)
    assert (fresh["status"], fresh["amount_usd"], fresh["kind"], fresh["attempts"]) == ("queued", "9750.00", "full", 0)
    assert payments._store.row_key(fresh) == payments._store.row_key(old)
    assert [r["outcome"] for r in ledger(wdb, first.run_id)] == ["Queued for payment"]
    assert run_batch("pay_all", "test").count == 1 and run_batch("pay_all", "test").count == 0
    assert run_row(wdb, first.run_id)["final_status"] == "Paid" and len(bank) == 1
    with pytest.raises(ReviewConflict):
        resume_review(first.run_id, "reject", "Sam", "Second thoughts on this one")


def test_approve_pays_at_once_when_delay_is_off(wdb, bank):
    first, _ = _pulled(wdb)
    save_payment_timing(PaymentTiming(delay_payments=False), "test")
    result = resume_review(first.run_id, "approve", "Dana", RATIONALE)
    assert result.final_status == "Paid" and bank == [("Northwind Fabrication LLC", payments.revisions.money("9750"))]


def test_reject_closes_it(wdb):
    first, _ = _pulled(wdb)
    result = resume_review(first.run_id, "reject", "Dana", "Split invoicing to dodge VP review")
    assert (result.status, result.final_status, result.decided_by) == ("Resolved", "Rejected", "Dana")
    assert [r["status"] for r in queue_rows(wdb, first.run_id)] == ["cancelled"]
    assert [r["outcome"] for r in ledger(wdb, first.run_id)] == ["Rejected"]
    [rejection] = trail(first.run_id, "rejection.recorded")
    assert rejection["rationale"] == "Split invoicing to dodge VP review"
    assert [f["code"] for f in rejection["findings"]] == ["PAYEE_CUMULATIVE_THRESHOLD"]
    assert run_batch("pay_all", "test").count == 0
    with pytest.raises(ReviewConflict):
        resume_review(first.run_id, "approve", "Sam", "Second thoughts on this one")


def test_reviewer_decision_on_the_trigger_does_not_flag_again(wdb):
    first, second = _pulled(wdb)
    resume_review(first.run_id, "approve", "Dana", RATIONALE)
    result = resume_review(second.run_id, "approve", "Dana", RATIONALE)
    assert result.status == "Queued for payment"
    assert run_row(wdb, first.run_id)["status"] == "Queued for payment"  # not pulled a second time
    assert run_batch("pay_all", "test").count == 2
