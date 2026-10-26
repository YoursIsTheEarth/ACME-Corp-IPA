"""Payee threshold holds over the API: the review view, decisions, the pull events, and retroactive flags."""

import httpx

from api_helpers import live_server, run, upload, wait_for, wait_idle
from test_admin_endpoints import put
from test_events import post_files, sse
from test_reviews import RATIONALE, review

SPLIT = ("invoice_1018.txt", "invoice_1019.json")


def review_rows(client):
    return {r["invoice_number"]: r for r in client.get("/api/invoices?view=review").json()["rows"]}


def test_review_view_shows_the_payee_total_and_contributors(client):
    first, second = upload(client, *SPLIT)
    rows = review_rows(client)
    pulled = rows["INV-1018"]
    assert (pulled["id"], pulled["hold_kind"], pulled["reason"], pulled["pulled"]) == (
        first, "payee_threshold", "Payee cumulative threshold", True)
    threshold = pulled["payee_threshold"]
    assert (threshold["total_usd"], threshold["threshold_usd"], threshold["window_days"]) == (
        "19250.00", "10000.00", 30)
    assert (threshold["window_start"], threshold["window_end"]) == ("2026-02-02", "2026-03-03")
    assert [(i["invoice_number"], i["invoice_date"], i["amount_usd"], i["status"], i["run_id"])
            for i in threshold["invoices"]] == [("INV-1018", "2026-02-02", "9750.00", "Awaiting review", first),
                                                ("INV-1019", "2026-02-09", "9500.00", "Awaiting review", second)]
    [finding] = pulled["findings"]
    assert finding["code"] == "PAYEE_CUMULATIVE_THRESHOLD" and "$19,250.00" in finding["message"]
    trigger = rows["INV-1019"]
    assert (trigger["hold_kind"], trigger["pulled"], trigger["payee_threshold"]["total_usd"]) == (
        "warning", False, "19250.00")
    assert rows.keys() == {"INV-1018", "INV-1019"}
    assert client.get("/api/payment-queue").json()["count"] == 0


def test_held_rows_show_the_latest_total(client):
    upload(client, *SPLIT, "invoice_1020.csv")
    rows = review_rows(client)
    for number in ("INV-1018", "INV-1019", "INV-1020"):
        assert rows[number]["payee_threshold"]["total_usd"] == "29000.00", number
        assert "$29,000.00" in next(f["message"] for f in rows[number]["findings"]
                                    if f["code"] == "PAYEE_CUMULATIVE_THRESHOLD")


def test_approve_requeues_then_a_second_decision_is_409(client):
    first, _ = upload(client, *SPLIT)
    assert review(client, first).status_code == 200
    wait_idle(client)
    [row] = client.get("/api/payment-queue").json()["rows"]
    assert (row["run_id"], row["status"], row["amount_usd"], row["approved_by"]) == (first, "queued", "9750.00", "Dana")
    assert "INV-1018" not in review_rows(client)
    response = review(client, first, decision="reject")
    assert response.status_code == 409


def test_reject_resolves_rejected(client):
    first, _ = upload(client, *SPLIT)
    assert review(client, first, decision="reject").status_code == 200
    wait_idle(client)
    detail = run(client, first)
    assert (detail["status"], detail["final_status"]) == ("Resolved", "Rejected")
    assert client.get("/api/payment-queue").json()["count"] == 0


def test_pull_is_announced():
    with live_server() as base, sse(base) as received, httpx.Client() as http:
        first, _ = post_files(http, base, *SPLIT)
        wait_for(lambda: any(n == "payment.cancelled" for n, _ in received))
        [cancelled] = [d for n, d in received if n == "payment.cancelled"]
        assert (cancelled["run_id"], cancelled["reason"]) == (first, "payee_threshold")
        wait_for(lambda: [d for n, d in received if n == "invoice.stage_changed" and d["run_id"] == first
                          and d["status"] == "Awaiting review"])
        [pulled] = [d for n, d in received if n == "invoice.stage_changed" and d["run_id"] == first
                    and d["status"] == "Awaiting review"]
        assert pulled["invoice"]["status"] == "Awaiting review"


def test_paid_invoice_detail_and_audit_show_the_retroactive_flag(client):
    assert put(client, delay_payments=False).status_code == 200
    first, second = upload(client, *SPLIT)
    detail = run(client, first)
    assert detail["final_status"] == "Paid"
    [flag] = [e for e in detail["timeline"] if e["event"] == "finding.retroactive"]
    assert flag["payload"]["triggered_by"] == {"run_id": second, "invoice_number": "INV-1019"}
    assert flag["payload"]["total"] == "19250.00" and flag["ts"]
    assert "PAYEE_CUMULATIVE_THRESHOLD" in {f["code"] for f in detail["findings"]}
    [audit] = [r for r in client.get("/api/invoices?view=audit").json()["rows"] if r["id"] == first]
    assert audit["final_status"] == "Paid"
    assert "PAYEE_CUMULATIVE_THRESHOLD" in {f["code"] for f in audit["key_findings"]}
