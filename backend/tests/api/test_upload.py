"""Upload intake, worker, and CLI parity (tasks 2.1-2.3)."""

import time

import pytest

from api_helpers import INVOICES, file_part, upload, wait_idle
from test_golden import GOLDEN_TABLE, OUTCOME_OF_STATUS


def test_multi_file_upload_returns_202_fast(client, conn):
    started = time.monotonic()
    response = client.post("/api/invoices", files=[file_part("invoice_1001.txt"), file_part("invoice_1006.csv")])
    elapsed = time.monotonic() - started
    assert response.status_code == 202 and elapsed < 1.0
    files = response.json()["files"]
    assert [(f["file_name"], f["status"]) for f in files] == [
        ("invoice_1001.txt", "Uploaded"), ("invoice_1006.csv", "Uploaded")]
    assert all(f["id"] for f in files)
    for f in files:
        row = conn.execute("SELECT * FROM invoice_runs WHERE id = ?", (f["id"],)).fetchone()
        assert row["file_name"] == f["file_name"]
        assert row["stored_path"].endswith(f"{f['id']}/{f['file_name']}")
    wait_idle(client)


def test_mixed_valid_and_invalid_files(client, conn):
    big = b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024 + 1)
    response = client.post("/api/invoices", files=[
        file_part("invoice_1001.txt"), ("files", ("notes.docx", b"hello")), ("files", ("blank.txt", b"")),
        ("files", ("big.pdf", big)),
    ])
    assert response.status_code == 202
    files = {f["file_name"]: f for f in response.json()["files"]}
    assert files["invoice_1001.txt"]["status"] == "Uploaded" and files["invoice_1001.txt"]["id"]
    for name, reason in (("notes.docx", "Unsupported file type"), ("blank.txt", "Empty file"),
                         ("big.pdf", "over 10 MB")):
        assert files[name]["status"] == "rejected" and files[name]["id"] is None
        assert reason in files[name]["error"]
    assert conn.execute("SELECT COUNT(*) FROM invoice_runs").fetchone()[0] == 1
    wait_idle(client)


def test_exactly_10_mb_is_accepted(client):
    response = client.post("/api/invoices", files=[("files", ("edge.txt", b"x" * (10 * 1024 * 1024)))])
    assert response.json()["files"][0]["status"] == "Uploaded"
    wait_idle(client)


def test_request_without_files_is_422(client):
    assert client.post("/api/invoices").status_code == 422
    assert client.post("/api/invoices", data={"note": "nothing"}).status_code == 422


def test_single_file_field_name_is_accepted(client):
    response = client.post("/api/invoices", files=[("file", ("invoice_1001.txt", (INVOICES / "invoice_1001.txt").read_bytes()))])
    assert response.status_code == 202 and response.json()["files"][0]["status"] == "Uploaded"
    wait_idle(client)


def test_1002_rejected_like_the_cli(client):
    [run_id] = upload(client, "invoice_1002.txt")
    detail = client.get(f"/api/invoices/{run_id}").json()
    assert detail["final_status"] == "Rejected"
    assert "STOCK_EXCEEDED" in {f["code"] for f in detail["findings"]}


def test_stage_progression_is_written(client, conn):
    [run_id] = upload(client, "invoice_1001.txt", wait=False)
    seen = set()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        row = next((r for r in client.get("/api/invoices?view=queue").json()["rows"] if r["id"] == run_id), None)
        if row is None:
            break
        seen.add(row["stage"])
        time.sleep(0.01)
    wait_idle(client)
    assert seen <= {"Uploaded", "Extracting", "Validating", "Deciding"} and seen
    events = [r["event"] for r in conn.execute("SELECT event FROM audit_log WHERE run_id = ?", (run_id,))]
    assert "ingestion.result" in events and "validation.findings" in events and "approval.decision" in events


# --- 2.3 parity with the golden suite -----------------------------------------------------------

@pytest.mark.parametrize("name", list(GOLDEN_TABLE))
def test_api_matches_golden_outcomes(api_golden, name):
    expected = GOLDEN_TABLE[name][0]
    run = api_golden["runs"][name]
    outcome = "NEEDS_REVIEW" if run["status"] == "Awaiting review" else OUTCOME_OF_STATUS.get(run["final_status"])
    assert outcome == expected


def test_api_golden_batch(api_golden):
    batch = api_golden["batches"]["rows"][0]
    assert (batch["batch_id"], batch["trigger"], batch["released_by"]) == (api_golden["batch"]["batch_id"], "pay_all", "Dana")
    assert (batch["count"], batch["total_usd"], batch["failed_count"]) == (7, "37620.00", 0)
    assert api_golden["queue"]["count"] == 7 and api_golden["queue"]["total_usd"] == "37620.00"
