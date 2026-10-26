"""Review resume: validation, conflicts, credit holds, payment-failure holds, active model (tasks 4.1-4.4)."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from acme.payments import mock_bank
from acme.settings import get_settings
from acme.workflow import create_run
from api_helpers import INVOICES, open_client, pay, upload, wait_idle
from workflow_helpers import inv_1004

RATIONALE = "Rush pricing agreed by procurement"


@pytest.fixture
def held(client):
    [run_id] = upload(client, "invoice_1010.txt")
    return run_id


def review(client, run_id, decision="approve", reviewer="Dana", rationale=RATIONALE):
    return client.post(f"/api/invoices/{run_id}/review",
                       json={"decision": decision, "reviewer": reviewer, "rationale": rationale})


def status(conn, run_id):
    return conn.execute("SELECT status, final_status FROM invoice_runs WHERE id = ?", (run_id,)).fetchone()


# --- 4.1 ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"decision": "approve", "reviewer": "    ", "rationale": RATIONALE},
    {"decision": "approve", "reviewer": "x" * 51, "rationale": RATIONALE},
    {"decision": "approve", "reviewer": "Dana", "rationale": "x" * 14},
    {"decision": "approve", "reviewer": "Dana", "rationale": "   short text   "},
    {"decision": "maybe", "reviewer": "Dana", "rationale": RATIONALE},
    {"reviewer": "Dana", "rationale": RATIONALE},
])
def test_invalid_review_is_422_and_changes_nothing(client, conn, held, body):
    response = client.post(f"/api/invoices/{held}/review", json=body)
    assert response.status_code == 422
    assert status(conn, held)["status"] == "Awaiting review"
    assert conn.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 0


def test_padded_name_is_stored_trimmed(client, conn, held):
    response = review(client, held, reviewer="  Dana  ")
    assert response.status_code == 200 and response.json()["reviewer"] == "Dana"
    wait_idle(client)
    assert conn.execute("SELECT reviewer FROM review_decisions").fetchone()[0] == "Dana"


def test_review_of_unknown_invoice_is_404(client):
    assert review(client, "does-not-exist").status_code == 404


# --- 4.2 ---------------------------------------------------------------------------------------

def test_approve_queues_a_payment(client, conn, held):
    response = review(client, held)
    assert response.status_code == 200 and response.json()["status"] == "Resuming"
    wait_idle(client)
    assert held not in {r["id"] for r in client.get("/api/invoices?view=review").json()["rows"]}
    assert held not in {r["id"] for r in client.get("/api/invoices?view=queue").json()["rows"]}
    [row] = client.get("/api/payment-queue").json()["rows"]
    assert (row["run_id"], row["status"], row["approved_by"], row["amount_usd"]) == (held, "queued", "Dana", "7185.00")
    timeline = client.get(f"/api/invoices/{held}").json()["timeline"]
    decision = [e for e in timeline if e["event"] == "review.decision"]
    assert decision[0]["payload"] == {"decision": "approve", "reviewer": "Dana", "rationale": RATIONALE}


def test_reject_resolves_rejected(client, held):
    assert review(client, held, "reject", rationale="Vendor would not honor list price").status_code == 200
    wait_idle(client)
    [row] = [r for r in client.get("/api/invoices?view=audit").json()["rows"] if r["id"] == held]
    assert (row["final_status"], row["decided_by"]) == ("Rejected", "Dana")
    assert client.get("/api/payment-queue").json()["rows"] == []


def test_concurrent_decisions_one_wins(client, conn, held):
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda name: review(client, held, reviewer=name), ["Dana", "Sam"]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    conflict = next(r for r in responses if r.status_code == 409).json()["detail"]
    assert conflict["status"] in ("Resuming", "Queued for payment")
    wait_idle(client)
    assert conn.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 1
    assert len(client.get("/api/payment-queue").json()["rows"]) == 1
    assert review(client, held).status_code == 409  # already decided


def test_review_of_processing_invoice_is_409(client, conn):
    run_id = create_run(INVOICES / "invoice_1001.txt")
    conn.execute("UPDATE invoice_runs SET stage = 'Validating', status = 'Processing' WHERE id = ?", (run_id,))
    conn.commit()
    response = review(client, run_id)
    assert response.status_code == 409 and response.json()["detail"]["status"] == "Processing"
    assert status(conn, run_id)["status"] == "Processing"


# --- 4.3 ---------------------------------------------------------------------------------------

def test_credit_hold_confirmed(client, conn, tmp_path):
    upload(client, "invoice_1004.json")
    pay(client)  # INV-1004 paid $1,890.00
    lower = inv_1004(tmp_path, "inv_1004_r1.json", "R1", [("WidgetA", 3, 250.0), ("WidgetB", 1, 500.0)])
    [revision] = upload(client, lower)  # $1,350.00
    [item] = client.get("/api/invoices?view=review").json()["rows"]
    assert (item["id"], item["hold_kind"], item["overpaid_usd"], item["paid_amount_usd"]) == (
        revision, "credit", "540.00", "1890.00")
    assert review(client, revision, rationale="Credit note CN-88 for $540 agreed with vendor").status_code == 200
    wait_idle(client)
    assert tuple(status(conn, revision)) == ("Resolved", "Credit confirmed")
    assert conn.execute("SELECT COUNT(*) FROM payment_queue WHERE run_id = ?", (revision,)).fetchone()[0] == 0
    assert client.get("/api/payment-queue").json()["rows"] == []


def test_credit_hold_reject_revision(client, conn, tmp_path):
    upload(client, "invoice_1004.json")
    pay(client)
    lower = inv_1004(tmp_path, "inv_1004_r1.json", "R1", [("WidgetA", 3, 250.0), ("WidgetB", 1, 500.0)])
    [revision] = upload(client, lower)
    assert review(client, revision, "reject", rationale="Vendor withdrew the revision").status_code == 200
    wait_idle(client)
    assert tuple(status(conn, revision)) == ("Resolved", "Rejected")
    assert client.get("/api/payment-queue").json()["rows"] == []


# --- 4.4 ---------------------------------------------------------------------------------------

def test_payment_failure_hold_and_requeue(client, conn):
    [run_id] = upload(client, "invoice_1001.txt")
    mock_bank.fail_next(3, "bank timeout")
    for attempt in (1, 2):
        pay(client)
        [row] = client.get("/api/payment-queue").json()["rows"]
        assert (row["status"], row["attempts"], row["last_error"]) == ("failed", attempt, "PaymentError: bank timeout")
    pay(client)
    assert client.get("/api/payment-queue").json()["rows"] == []
    [item] = client.get("/api/invoices?view=review").json()["rows"]
    assert (item["id"], item["hold_kind"], item["reason"]) == (run_id, "payment_failure", "Payment failed")
    assert item["last_error"] == "PaymentError: bank timeout" and item["attempts"] == 3
    assert review(client, run_id, rationale="Bank outage resolved, retry it").status_code == 200
    wait_idle(client)
    [row] = client.get("/api/payment-queue").json()["rows"]
    assert (row["run_id"], row["status"], row["attempts"]) == (run_id, "queued", 0)
    assert client.get("/api/invoices?view=review").json()["rows"] == []


def test_stats_reports_configured_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    get_settings.cache_clear()
    with open_client() as client:
        llm = client.get("/api/stats").json()["llm"]
    assert (llm["provider"], llm["model"]) == ("claude", "claude-sonnet-5-5")
    assert llm["roles"]["critic"] == {"provider": "claude", "model": "claude-sonnet-5-5"}


def test_stats_reports_offline_model(client):
    llm = client.get("/api/stats").json()["llm"]
    assert llm["provider"] == "offline" and llm["model"]
