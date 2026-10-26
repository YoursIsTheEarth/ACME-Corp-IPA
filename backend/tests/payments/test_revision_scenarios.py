"""The 8 payment-processing scenarios end to end through the disposition tools and the executor.

Revisions are copies of INV-1004 ($1,890.00) with edited totals; approval uses the real policy.
"""

import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from acme.approval import apply_policy
from acme.models import Decision, Outcome
from acme.payments import (BatchAlreadyRunning, enqueue_review, idle_batch_due, is_batch_running,
                           load_runs_snapshot, mock_bank, payable_count, queue_payment, record_processed,
                           record_rejection, review_hold, run_batch, supersede_original)
from acme.settings import get_settings
from acme.validation import ValidationContext, detect_duplicate
from payment_helpers import APPROVE, approve, make_run, queue_rows, revised, run_row


def dispose(conn, run_id, invoice):
    """Disposition as the workflow does it: validation's revision context -> policy -> disposition tools."""
    make_run(conn, run_id)
    findings, revision_ctx = detect_duplicate(invoice, ValidationContext.load(conn))
    floor = apply_policy(invoice, findings, revision_ctx).floor
    record_processed(run_id, invoice, floor)
    if revision_ctx is not None:
        supersede_original(invoice, run_id)
    if floor == Outcome.APPROVE:
        return queue_payment(run_id, invoice, APPROVE)
    if floor == Outcome.NEEDS_REVIEW:
        overpaid = revision_ctx.paid_amount - invoice.total
        return enqueue_review(run_id, f"Revision lowers a paid total: {overpaid} overpaid", "credit",
                              {"overpaid": overpaid})
    return record_rejection(run_id, Decision(outcome=floor, rationale="Rule failed."), findings)


@pytest.fixture
def paid_1004(pdb, golden):
    approve(pdb, "r-1004", golden["invoice_1004.json"])
    assert run_batch("pay_all", "Dana").count == 1
    return golden["invoice_1004.json"]


def amounts(conn):
    return [(r["run_id"], r["kind"], r["amount_usd"], r["status"]) for r in queue_rows(conn)]


def test_queued_revision_replaces_original(pdb, golden, bank):
    approve(pdb, "r-1004", golden["invoice_1004.json"])
    result = dispose(pdb, "r-1004r", golden["invoice_1004_revised.json"])
    assert (result.kind, result.amount) == ("replacement", Decimal("5940.00"))
    assert run_row(pdb, "r-1004")["final_status"] == "Superseded"
    assert run_batch("pay_all", "Dana").total_usd == Decimal("5940.00")
    assert bank == [("Precision Parts Ltd.", Decimal("5940.00"))]


def test_paid_higher_pays_delta(pdb, paid_1004, bank):
    dispose(pdb, "r-1004r", revised(paid_1004, "2390.00"))
    assert amounts(pdb)[-1] == ("r-1004r", "delta", "500.00", "queued")
    result = run_batch("pay_all", "Dana")
    assert (result.count, result.total_usd) == (1, Decimal("500.00"))
    keys = [r[0] for r in pdb.execute("SELECT idempotency_key FROM payments ORDER BY id")]
    assert keys == ["precision parts ltd.|INV-1004|0", "precision parts ltd.|INV-1004|1|delta"]
    assert run_row(pdb, "r-1004r")["final_status"] == "Revised" and run_row(pdb, "r-1004")["final_status"] == "Paid"


def test_paid_lower_is_held_for_credit(pdb, paid_1004, bank):
    dispose(pdb, "r-1004r", revised(paid_1004, "1500.00"))
    assert [r[0] for r in amounts(pdb)] == ["r-1004"]
    hold = review_hold("r-1004r")
    assert hold.kind == "credit" and "390.00 overpaid" in hold.reason
    assert run_row(pdb, "r-1004r")["status"] == "Awaiting review"


def test_paid_lower_race_through_queue_payment_is_held(pdb, paid_1004):
    make_run(pdb, "r-1004r")
    result = queue_payment("r-1004r", revised(paid_1004, "1500.00"), APPROVE)
    assert (result.action, result.amount) == ("held", Decimal("390.00"))
    assert review_hold("r-1004r").details["overpaid"] == "390.00"


def test_paid_same_is_revised(pdb, paid_1004, bank):
    result = dispose(pdb, "r-1004r", revised(paid_1004, "1890.00"))
    assert result.action == "revised" and run_row(pdb, "r-1004r")["final_status"] == "Revised"
    assert [r[0] for r in amounts(pdb)] == ["r-1004"]


def test_queued_revision_failing_a_rule(pdb, golden, bank):
    approve(pdb, "r-1004", golden["invoice_1004.json"])
    bad = golden["invoice_1004_revised.json"]  # judged REJECT (e.g. a stock overrun) by validation/approval
    make_run(pdb, "r-1004r")
    record_processed("r-1004r", bad, Outcome.REJECT)
    supersede_original(bad, "r-1004r")
    record_rejection("r-1004r", Decision(outcome=Outcome.REJECT, rationale="Stock exceeded."), [])
    assert run_row(pdb, "r-1004")["final_status"] == "Superseded"
    assert run_row(pdb, "r-1004r")["final_status"] == "Rejected"
    assert run_batch("pay_all", "Dana").count == 0 and bank == []


def test_idle_trigger_fires_after_upload_settles(pdb, golden, bank):
    settings = get_settings()
    approve(pdb, "r-1001", golden["invoice_1001.txt"])
    make_run(pdb, "r-1010")
    enqueue_review("r-1010", "Price variance", "warning")
    make_run(pdb, "r-1006", status="Processing", stage="Extracting")
    now = datetime.now(timezone.utc)

    def due(at):
        return idle_batch_due(at, load_runs_snapshot(pdb), payable_count(pdb, settings.payment_max_attempts),
                              is_batch_running(), settings)
    assert not due(now + timedelta(seconds=120))  # r-1006 still extracting
    pdb.execute("UPDATE invoice_runs SET stage = 'Resolved', status = 'Resolved' WHERE id = 'r-1006'")
    pdb.commit()
    assert not due(now)
    assert due(now + timedelta(seconds=61))  # INV-1010 Awaiting review does not block
    assert run_batch("idle").released_by == "System" and len(bank) == 1
    assert not due(now + timedelta(seconds=600))  # queue empty


def test_concurrent_pay_all(pdb, golden, bank, monkeypatch):
    for name in ("invoice_1001.txt", "invoice_1006.csv", "invoice_1015.csv"):
        approve(pdb, name, golden[name])
    started, release = threading.Event(), threading.Event()
    real = mock_bank.mock_payment

    def slow(vendor, amount):
        started.set()
        release.wait(10)
        return real(vendor, amount)
    monkeypatch.setattr(mock_bank, "mock_payment", slow)
    outcomes = []
    first = threading.Thread(target=lambda: outcomes.append(run_batch("pay_all", "Dana")))
    first.start()
    started.wait(5)
    with pytest.raises(BatchAlreadyRunning):
        run_batch("pay_all", "Lee")
    release.set()
    first.join(10)
    assert outcomes[0].count == 3 and len(bank) == 3
    assert run_batch("pay_all", "Lee").count == 0


def test_payment_failure_retries_escalates_and_requeues(pdb, golden, bank):
    from acme.payments import resume_payment_failure
    approve(pdb, "r-1001", golden["invoice_1001.txt"])
    mock_bank.fail_next(3, "bank down")
    for _ in range(3):
        run_batch("pay_all", "Dana")
    assert review_hold("r-1001").kind == "payment_failure"
    assert run_batch("pay_all", "Dana").results == []
    resume_payment_failure("r-1001", approve=True, reviewer="Dana", rationale="Retry after bank fix.")
    assert run_batch("pay_all", "Dana").count == 1
    assert len(bank) == 4 and run_row(pdb, "r-1001")["final_status"] == "Paid"
