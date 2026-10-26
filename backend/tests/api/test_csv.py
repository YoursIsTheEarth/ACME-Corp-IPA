"""CSV export (task 8.1): same rows as the JSON endpoints for the same filters."""

import csv
import io

from api_helpers import pay, upload


def parse(response):
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    return list(csv.DictReader(io.StringIO(response.text)))


def test_payments_csv_matches_json_for_vendor_filter(client):
    upload(client, "invoice_1001.txt", "invoice_1006.csv", "invoice_1015.csv")
    pay(client)
    vendor = client.get("/api/payments").json()["rows"][0]["vendor"]
    params = {"vendor": vendor}
    rows = client.get("/api/payments", params=params).json()["rows"]
    exported = parse(client.get("/api/payments.csv", params=params))
    assert 0 < len(rows) < 3
    assert [(r["payment_id"], r["vendor"], r["amount_usd"], r["idempotency_key"], r["released_by"]) for r in exported] == [
        (r["payment_id"], r["vendor"], r["amount_usd"], r["idempotency_key"], r["released_by"]) for r in rows]


def test_invoices_csv_matches_audit_filter(client):
    upload(client, "invoice_1002.txt", "invoice_1003.txt", "invoice_1009.json")
    params = {"status": "Rejected", "search": "100"}
    rows = client.get("/api/invoices", params={"view": "audit", **params}).json()["rows"]
    exported = parse(client.get("/api/invoices.csv", params=params))
    assert len(rows) == 3
    assert [(r["id"], r["final_status"], r["invoice_number"]) for r in exported] == [
        (r["id"], r["final_status"], r["invoice_number"]) for r in rows]
    assert exported[0]["key_findings"] == ";".join(f["code"] for f in rows[0]["key_findings"])
    assert parse(client.get("/api/invoices.csv", params={"status": "Paid"})) == []


def test_empty_export_has_header_row(client):
    response = client.get("/api/payments.csv")
    assert response.text.splitlines()[0].startswith("payment_id,invoice_number")
