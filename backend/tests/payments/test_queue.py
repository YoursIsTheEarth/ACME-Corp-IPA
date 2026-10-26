from decimal import Decimal

import pytest

from acme.logging import read_trace
from acme.models import Decision, Finding, FindingCode as C, Outcome
from acme.payments import (enqueue_review, queue_payment, record_processed, record_rejection, review_hold,
                           supersede_original)
from acme.validation import ValidationContext, content_hash
from payment_helpers import APPROVE, approve, make_run, queue_rows, revised, run_row


def f(code, **evidence):
    return Finding(code=code, severity=code.severity, message=code.value, evidence=evidence)


def pay(conn, run_id, amount):
    """Mark a run's queued row paid in the ledger (as a finished batch would)."""
    row = queue_rows(conn, run_id)[0]
    conn.execute("INSERT INTO payments (idempotency_key, vendor, amount_usd, paid_at) VALUES (?, ?, ?, 'x')",
                 (f"{row['vendor'].casefold()}|{row['invoice_number']}|{row['revision']}", row["vendor"], amount))
    conn.execute("UPDATE payment_queue SET status = 'paid' WHERE id = ?", (row["id"],))
    conn.execute("UPDATE invoice_runs SET final_status = 'Paid' WHERE id = ?", (run_id,))
    conn.commit()


# --- 3.1 queue_payment ------------------------------------------------------------------

def test_inv_1001_is_queued_in_full_and_not_paid(pdb, golden, bank):
    result = approve(pdb, "r-1001", golden["invoice_1001.txt"])
    assert (result.action, result.kind, result.amount) == ("queued", "full", Decimal("5000.00"))
    [row] = queue_rows(pdb)
    assert (row["status"], row["kind"], row["amount_usd"], row["attempts"], row["revision"]) == (
        "queued", "full", "5000.00", 0, 0)
    assert row["vendor"] == "Widgets Inc." and row["queued_at"]
    assert pdb.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0 and bank == []
    assert run_row(pdb, "r-1001")["status"] == "Queued for payment"


def test_eur_invoice_is_queued_in_usd(pdb, golden):
    approve(pdb, "r-1014", golden["invoice_1014.xml"])
    assert queue_rows(pdb)[0]["amount_usd"] == "4455.00"


def test_queue_payment_is_idempotent_per_run(pdb, golden):
    first = approve(pdb, "r-1001", golden["invoice_1001.txt"])
    again = queue_payment("r-1001", golden["invoice_1001.txt"], APPROVE)
    assert again.row_id == first.row_id and len(queue_rows(pdb)) == 1


def test_queue_payment_needs_approve(pdb, golden):
    with pytest.raises(ValueError):
        queue_payment("r", golden["invoice_1001.txt"], Decision(outcome=Outcome.REJECT, rationale="no"))


def test_r1_replaces_queued_original(pdb, golden):
    approve(pdb, "r-1004", golden["invoice_1004.json"])
    make_run(pdb, "r-1004r")
    record_processed("r-1004r", golden["invoice_1004_revised.json"], Outcome.APPROVE)
    assert supersede_original(golden["invoice_1004_revised.json"], "r-1004r") == ["r-1004"]
    result = queue_payment("r-1004r", golden["invoice_1004_revised.json"], APPROVE)
    assert (result.kind, result.amount) == ("replacement", Decimal("5940.00"))
    assert [(r["run_id"], r["status"]) for r in queue_rows(pdb)] == [("r-1004", "cancelled"), ("r-1004r", "queued")]
    assert run_row(pdb, "r-1004")["final_status"] == "Superseded"


def test_delta_for_paid_original_with_higher_total(pdb, golden):
    approve(pdb, "r-1004", golden["invoice_1004.json"])
    pay(pdb, "r-1004", "1890.00")
    result = approve(pdb, "r-1004r", revised(golden["invoice_1004.json"], "2390.00"))
    assert (result.kind, result.amount) == ("delta", Decimal("500.00"))
    assert run_row(pdb, "r-1004")["final_status"] == "Paid"


# --- record_processed (the processed_invoices contract) ---------------------------------

def test_record_processed_writes_validation_contract(pdb, golden):
    invoice = golden["invoice_1011.txt"]
    make_run(pdb, "r-1011")
    record_processed("r-1011", invoice, Outcome.REJECT)
    row = pdb.execute("SELECT * FROM processed_invoices").fetchone()
    assert (row["vendor"], row["content_hash"], row["outcome"], row["run_id"]) == (
        ValidationContext.load(pdb).vendor_key(invoice.vendor_name), content_hash(invoice), "REJECT", "r-1011")
    run = run_row(pdb, "r-1011")
    assert (run["total_usd"], run["invoice_number"], run["vendor"]) == ("3000.00", "INV-1011", invoice.vendor_name)
    assert ValidationContext.load(pdb).processed[0].total == Decimal("3000.00")


def test_record_processed_keeps_the_first_claim_but_updates_its_own_row(pdb, golden):
    invoice = golden["invoice_1010.txt"]
    make_run(pdb, "r-a")
    make_run(pdb, "r-b")
    record_processed("r-a", invoice, Outcome.NEEDS_REVIEW)
    record_processed("r-b", invoice, Outcome.REJECT)  # a duplicate copy
    record_processed("r-a", invoice, Outcome.APPROVE)  # resumed after review
    assert [tuple(r) for r in pdb.execute("SELECT run_id, outcome FROM processed_invoices")] == [("r-a", "APPROVE")]


# --- 3.2 supersede_original -------------------------------------------------------------

@pytest.mark.parametrize("hold", ["queued", "held", "rejected"])
def test_supersede_unpaid_originals(pdb, golden, hold):
    original = golden["invoice_1004.json"]
    if hold == "queued":
        approve(pdb, "r-1004", original)
    else:
        make_run(pdb, "r-1004")
        record_processed("r-1004", original, Outcome.NEEDS_REVIEW if hold == "held" else Outcome.REJECT)
        if hold == "held":
            enqueue_review("r-1004", "Price variance 20%", "warning")
        else:
            record_rejection("r-1004", Decision(outcome=Outcome.REJECT, rationale="r"), [f(C.STOCK_EXCEEDED)])
    assert supersede_original(golden["invoice_1004_revised.json"], "r-1004r") == ["r-1004"]
    run = run_row(pdb, "r-1004")
    assert (run["final_status"], run["status"]) == ("Superseded", "Resolved")
    assert all(r["status"] == "cancelled" for r in queue_rows(pdb))
    [event] = [e for e in read_trace("r-1004", pdb) if e["event"] == "invoice.superseded"]
    assert event["payload"]["finding"]["code"] == "SUPERSEDED_BY_REVISION"
    assert event["payload"]["finding"]["evidence"]["revision_run_id"] == "r-1004r"


def test_supersede_leaves_paid_original(pdb, golden):
    approve(pdb, "r-1004", golden["invoice_1004.json"])
    pay(pdb, "r-1004", "1890.00")
    assert supersede_original(golden["invoice_1004_revised.json"], "r-1004r") == []
    assert run_row(pdb, "r-1004")["final_status"] == "Paid" and queue_rows(pdb)[0]["status"] == "paid"


def test_supersede_without_original_is_a_noop(pdb, golden):
    assert supersede_original(golden["invoice_1004_revised.json"], "r-1004r") == []


# --- 3.3 record_rejection ---------------------------------------------------------------

def test_inv_1002_rejection_is_logged(pdb, golden):
    make_run(pdb, "r-1002")
    record_processed("r-1002", golden["invoice_1002.txt"], Outcome.REJECT)
    decision = Decision(outcome=Outcome.REJECT, rationale="GadgetX quantity 20 exceeds stock 5.",
                        rules_applied=["CRITICAL_STOCK_EXCEEDED"], decided_by="Auto (rules)")
    finding = f(C.STOCK_EXCEEDED, sku="GadgetX", requested=20, stock=5)
    assert record_rejection("r-1002", decision, [finding]) == "Rejected"
    run = run_row(pdb, "r-1002")
    assert (run["final_status"], run["decided_by"]) == ("Rejected", "Auto (rules)") and run["completed_at"]
    [event] = [e for e in read_trace("r-1002", pdb) if e["event"] == "rejection.recorded"]
    payload = event["payload"]
    assert payload["rationale"] == decision.rationale and payload["invoice_number"] == "INV-1002"
    assert payload["rules_applied"] == ["CRITICAL_STOCK_EXCEEDED"]
    assert payload["findings"][0]["code"] == "STOCK_EXCEEDED" and payload["findings"][0]["evidence"]["stock"] == 5
    assert queue_rows(pdb) == []


def test_duplicate_is_logged_as_duplicate(pdb, golden):
    make_run(pdb, "r-1011t")
    decision = Decision(outcome=Outcome.REJECT, rationale="Already processed.", rules_applied=["CRITICAL_DUPLICATE"])
    assert record_rejection("r-1011t", decision, [f(C.DUPLICATE, original_run_id="r-1011p")]) == "Duplicate"
    assert run_row(pdb, "r-1011t")["final_status"] == "Duplicate"
    assert queue_rows(pdb) == [] and pdb.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


# --- 3.4 enqueue_review -----------------------------------------------------------------

@pytest.mark.parametrize("kind", ["warning", "credit", "payment_failure"])
def test_enqueue_review_shows_awaiting_review_with_reason(pdb, kind):
    make_run(pdb, "r-1010")
    enqueue_review("r-1010", "Price variance 20% on WidgetA", kind, {"note": 1})
    run = run_row(pdb, "r-1010")
    assert (run["status"], run["stage"], run["final_status"]) == ("Awaiting review", "Awaiting review", None)
    assert review_hold("r-1010").reason == "Price variance 20% on WidgetA"
    assert (review_hold("r-1010").kind, review_hold("r-1010").details) == (kind, {"note": 1})


def test_enqueue_review_rejects_unknown_kind(pdb):
    with pytest.raises(ValueError):
        enqueue_review("r", "x", "other")
    assert review_hold("r") is None
