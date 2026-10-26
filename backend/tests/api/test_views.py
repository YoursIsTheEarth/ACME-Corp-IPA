"""Read views: invoice lists, detail and file, payments, payment queue, stats (tasks 3.1-3.4)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from acme.admin import PaymentTiming, save_payment_timing
from acme.workflow import create_run
from api_helpers import INVOICES, pay, upload


def _set_stage(conn, run_id, stage, status="Processing"):
    conn.execute("UPDATE invoice_runs SET stage = ?, status = ? WHERE id = ?", (stage, status, run_id))
    conn.commit()


# --- 3.1 ---------------------------------------------------------------------------------------

def test_queue_view_shows_processing_and_held(client, conn):
    [held] = upload(client, "invoice_1010.txt")
    validating = create_run(INVOICES / "invoice_1001.txt")  # not enqueued: stays where we put it
    _set_stage(conn, validating, "Validating")
    body = client.get("/api/invoices?view=queue").json()
    assert body["view"] == "queue" and body["server_time"]
    rows = {r["id"]: r for r in body["rows"]}
    assert set(rows) == {held, validating}
    assert (rows[validating]["stage"], rows[validating]["status"]) == ("Validating", "Processing")
    assert (rows[held]["stage"], rows[held]["status"]) == ("Awaiting review", "Awaiting review")
    assert (rows[held]["invoice_number"], rows[held]["vendor"], rows[held]["amount_usd"]) == (
        "INV-1010", "Consolidated Materials Group", "7185.00")
    for key in ("file_name", "format", "uploaded_at", "time_in_stage_s", "stage_entered_at"):
        assert rows[held][key] is not None
    assert rows[validating]["invoice_number"] is None  # "Extracting..." in the UI


def test_awaiting_review_shows_in_queue_and_review(client):
    [held] = upload(client, "invoice_1010.txt")
    assert held in {r["id"] for r in client.get("/api/invoices?view=queue").json()["rows"]}
    [item] = client.get("/api/invoices?view=review").json()["rows"]
    assert item["id"] == held and item["hold_kind"] == "warning"
    assert "PRICE_VARIANCE" in {f["code"] for f in item["findings"]}
    assert all(f["message"] for f in item["findings"])
    assert item["ai_recommendation"] and item["ai_rationale"]
    assert item["waiting_since"] and item["waiting_s"] >= 0 and "PRICE_VARIANCE" in item["reason"]


def test_audit_view_filters(client):
    ids = dict(zip(["1001", "1002", "1003"], upload(client, "invoice_1001.txt", "invoice_1002.txt", "invoice_1003.txt")))
    all_rows = client.get("/api/invoices?view=audit").json()["rows"]
    assert {r["id"] for r in all_rows} == {ids["1002"], ids["1003"]}  # 1001 is queued for payment, not resolved
    today = date.today()
    params = {"view": "audit", "status": "Rejected", "date_from": str(today - timedelta(days=1)),
              "date_to": str(today + timedelta(days=1)), "search": "1002"}
    [row] = client.get("/api/invoices", params=params).json()["rows"]
    assert row["id"] == ids["1002"] and row["final_status"] == "Rejected" and row["decided_by"]
    assert row["key_findings"][0]["code"] == "STOCK_EXCEEDED" and row["completed_at"] and row["processing_s"] >= 0
    past = params | {"date_from": "2020-01-01", "date_to": "2020-01-02"}
    assert client.get("/api/invoices", params=past).json()["rows"] == []
    assert client.get("/api/invoices", params=params | {"status": "Paid"}).json()["rows"] == []


def test_unknown_or_missing_view_is_422(client):
    assert client.get("/api/invoices?view=other").status_code == 422
    assert client.get("/api/invoices").status_code == 422


def test_audit_key_findings_capped_at_three(api_golden):
    row = api_golden["before"][api_golden["ids"]["invoice_1009.json"]]
    assert len(row["key_findings"]) == 3 and row["findings_count"] >= 4
    superseded = api_golden["before"][api_golden["ids"]["invoice_1004.json"]]
    assert superseded["final_status"] == "Superseded"
    assert superseded["key_findings"][0]["code"] == "SUPERSEDED_BY_REVISION"


def test_audit_key_findings_unique_codes(api_golden):
    row = api_golden["before"][api_golden["ids"]["invoice_1013.json"]]
    codes = [f["code"] for f in row["key_findings"]]
    assert codes[0] == "STOCK_EXCEEDED" and len(codes) == len(set(codes))


# --- 3.2 ---------------------------------------------------------------------------------------

def test_detail_of_rejected_1009(api_golden):
    detail = api_golden["detail_1009"]
    assert detail["final_status"] == "Rejected"
    assert {"MISSING_VENDOR", "INVALID_QUANTITY", "MATH_MISMATCH", "MISSING_DUE_DATE"} <= {
        f["code"] for f in detail["findings"]}
    agents = {e["agent"] for e in detail["timeline"]}
    assert {"ingestion", "normalizer", "validation", "approval", "disposition"} <= agents
    assert detail["drafts"] and all(d["provider"] == "grok" and d["model"] for d in detail["drafts"])
    assert detail["rejection"]["final_status"] == "Rejected" and detail["invoice"]["invoice_number"] == "INV-1009"


def test_detail_of_paid_invoice_has_payment_and_drafts(client):
    [run_id] = upload(client, "invoice_1001.txt")
    pay(client)
    detail = client.get(f"/api/invoices/{run_id}").json()
    assert detail["final_status"] == "Paid" and detail["findings"] == []
    assert detail["invoice"]["vendor_name"] and detail["invoice"]["line_items"]
    assert [p["payment_id"] for p in detail["payments"]] == ["PAY-000001"]
    assert detail["timeline"][-1]["event"] == "payment.created"


def test_original_pdf_round_trip(client):
    original = (INVOICES / "invoice_1011.pdf").read_bytes()
    [run_id] = upload(client, "invoice_1011.pdf")
    response = client.get(f"/api/invoices/{run_id}/file")
    assert response.status_code == 200 and response.content == original
    assert response.headers["content-type"] == "application/pdf"
    text = upload(client, "invoice_1006.csv")[0]
    assert client.get(f"/api/invoices/{text}/file").headers["content-type"].startswith("text/csv")


def test_unknown_invoice_is_404(client):
    assert client.get("/api/invoices/does-not-exist").status_code == 404
    assert client.get("/api/invoices/does-not-exist/file").status_code == 404


# --- 3.3 ---------------------------------------------------------------------------------------

def test_payments_after_golden_batch(api_golden):
    payments = api_golden["payments"]
    assert payments["count"] == 7 and payments["total_usd"] == "37620.00" and payments["server_time"]
    rows = {r["invoice_number"]: r for r in payments["rows"]}
    eur = rows["INV-1014"]
    assert (eur["amount_usd"], eur["original_amount"], eur["original_currency"]) == ("4455.00", "4125.00", "EUR")
    usd = rows["INV-1001"]
    assert usd["original_currency"] is None and usd["original_amount"] is None
    for row in payments["rows"]:
        assert row["payment_id"].startswith("PAY-") and row["idempotency_key"] and row["paid_at"]
        assert (row["batch_id"], row["batch_trigger"], row["released_by"]) == (
            api_golden["batch"]["batch_id"], "pay_all", "Dana")
        assert row["approved_by"]
    assert rows["INV-1004"]["kind"] == "replacement" and rows["INV-1004"]["delta_label"] is None


def test_payments_filters_and_total(client):
    upload(client, "invoice_1001.txt", "invoice_1006.csv")
    pay(client)
    everything = client.get("/api/payments").json()
    assert everything["count"] == 2 and everything["total_usd"] == "7750.00"
    vendor = everything["rows"][0]["vendor"]
    one = client.get("/api/payments", params={"vendor": vendor[:5].lower()}).json()
    assert {r["vendor"] for r in one["rows"]} == {vendor}
    assert Decimal(one["total_usd"]) == sum(Decimal(r["amount_usd"]) for r in one["rows"])
    assert client.get("/api/payments", params={"date_to": "2020-01-01"}).json()["rows"] == []
    assert client.get("/api/payments", params={"date_from": "2020-01-01", "date_to": "2100-01-01"}).json()["count"] == 2


def test_payment_batches_history(api_golden):
    [batch] = api_golden["batches"]["rows"]
    assert batch["trigger_label"] == "Pay all" and batch["finished_at"] and batch["running"] is False


def test_delta_payment_label(client):
    upload(client, "invoice_1004.json")
    pay(client)
    upload(client, "invoice_1004_revised.json")
    [row] = client.get("/api/payment-queue").json()["rows"]
    assert (row["kind"], row["amount_usd"]) == ("delta", "4050.00")
    pay(client)
    delta = [r for r in client.get("/api/payments").json()["rows"] if r["kind"] == "delta"]
    assert [(r["delta_label"], r["invoice_total_usd"]) for r in delta] == [("Delta for R1", "5940.00")]


# --- 3.4 ---------------------------------------------------------------------------------------

def test_payment_queue_two_full_rows(client):
    save_payment_timing(PaymentTiming(pay_at_end_of_day=True), "Dana")  # delay on, end of day at the defaults
    upload(client, "invoice_1001.txt", "invoice_1006.csv")
    queue = client.get("/api/payment-queue").json()
    assert queue["count"] == 2 and queue["total_usd"] == "7750.00"
    assert [r["kind"] for r in queue["rows"]] == ["full", "full"]
    assert all(r["status"] == "queued" and r["attempts"] == 0 and r["approved_by"] for r in queue["rows"])
    assert (queue["delay_payments"], queue["pay_at_end_of_day"], queue["pay_when_queue_empty"]) == (True, True, True)
    assert queue["next_batch_label"].endswith("5:00 PM CT") and queue["timezone"] == "America/Chicago"
    assert queue["next_batch_at"].endswith(("-05:00", "-06:00")) and "T17:00:00" in queue["next_batch_at"]
    assert queue["batch_running"] is False and "auto_idle" not in queue


def test_payment_queue_mode_with_the_defaults(client):
    upload(client, "invoice_1001.txt")
    queue = client.get("/api/payment-queue").json()
    assert queue["count"] == 1
    assert (queue["delay_payments"], queue["pay_at_end_of_day"], queue["pay_when_queue_empty"]) == (True, False, True)
    assert (queue["next_batch_at"], queue["next_batch_label"], queue["timezone"]) == (None, None, "America/Chicago")


def test_payment_queue_mode_with_delay_off(client):
    save_payment_timing(PaymentTiming(delay_payments=False, pay_at_end_of_day=True), "Dana")
    upload(client, "invoice_1001.txt")
    queue = client.get("/api/payment-queue").json()
    assert (queue["delay_payments"], queue["next_batch_at"], queue["next_batch_label"]) == (False, None, None)
    assert queue["rows"] == [] and queue["count"] == 0  # paid at approval


def test_dates_use_the_admin_timezone(client):
    """Audit date filters (and stats' "today") use the admin end-of-day timezone, not UTC."""
    [rejected] = upload(client, "invoice_1002.txt")
    east = datetime.now(timezone.utc).astimezone(ZoneInfo("Etc/GMT-14")).date()  # UTC+14: 26 h ahead of UTC-12
    params = {"view": "audit", "date_from": str(east), "date_to": str(east)}
    for tz, expected in (("Etc/GMT-14", [rejected]), ("Etc/GMT+12", [])):
        save_payment_timing(PaymentTiming(end_of_day_timezone=tz), "Dana")
        assert [r["id"] for r in client.get("/api/invoices", params=params).json()["rows"]] == expected, tz
        assert client.get("/api/stats").json()["rejected_today"] == 1


def test_audit_status_filter_revised(client):
    save_payment_timing(PaymentTiming(delay_payments=False), "Dana")
    original, revision = upload(client, "invoice_1004.json", "invoice_1004_revised.json")
    rows = client.get("/api/invoices", params={"view": "audit", "status": "Revised"}).json()["rows"]
    assert [(r["id"], r["final_status"]) for r in rows] == [(revision, "Revised")]
    paid = client.get("/api/invoices", params={"view": "audit", "status": "Paid"}).json()["rows"]
    assert [r["id"] for r in paid] == [original]


def test_revision_replaces_queued_row(client):
    upload(client, "invoice_1004.json", "invoice_1004_revised.json")
    [row] = client.get("/api/payment-queue").json()["rows"]
    assert (row["invoice_number"], row["revision"], row["kind"], row["amount_usd"]) == (
        "INV-1004", 1, "replacement", "5940.00")


def test_badge_counts(client):
    upload(client, "invoice_1001.txt", "invoice_1006.csv", "invoice_1010.txt")
    for _ in range(3):
        create_run(INVOICES / "invoice_1015.csv")  # processing, not enqueued
    stats = client.get("/api/stats").json()
    assert (stats["in_queue"], stats["awaiting_review"], stats["payment_queue"]) == (4, 1, 2)
    assert stats["processing"] == 3 and stats["paid_today"] == 0 and stats["rejected_today"] == 0
    assert stats["server_time"]
