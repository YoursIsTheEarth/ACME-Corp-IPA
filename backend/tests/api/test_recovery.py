"""Restart durability (tasks 6.1, 6.2): each `open_client()` is a fresh app and lifespan on the same acme.db."""

from acme.payments._store import row_key
from acme.workflow import create_run, record_review
from api_helpers import INVOICES, open_client, pay, upload, wait_idle

RATIONALE = "Rush pricing agreed by procurement"


def test_review_after_restart(conn):
    with open_client() as client:
        [held] = upload(client, "invoice_1010.txt")
        assert client.get("/api/stats").json()["awaiting_review"] == 1
    with open_client() as client:  # restart
        [item] = client.get("/api/invoices?view=review").json()["rows"]
        assert item["id"] == held
        response = client.post(f"/api/invoices/{held}/review",
                               json={"decision": "approve", "reviewer": "Dana", "rationale": RATIONALE})
        assert response.status_code == 200
        wait_idle(client)
        [row] = client.get("/api/payment-queue").json()["rows"]
        assert (row["run_id"], row["status"], row["approved_by"]) == (held, "queued", "Dana")
    # the original run resumed: one run, one checkpoint thread
    assert conn.execute("SELECT COUNT(*) FROM invoice_runs").fetchone()[0] == 1


def test_orphaned_runs_are_processed_on_startup(conn):
    with open_client() as client:
        pass  # create and seed the db
    stuck = create_run(INVOICES / "invoice_1002.txt")
    conn.execute("UPDATE invoice_runs SET stage = 'Validating', status = 'Processing' WHERE id = ?", (stuck,))
    conn.commit()
    with open_client() as client:
        wait_idle(client)
        [row] = [r for r in client.get("/api/invoices?view=audit").json()["rows"] if r["id"] == stuck]
        assert row["final_status"] == "Rejected"


def test_resuming_runs_are_resubmitted_on_startup(conn):
    with open_client() as client:
        [held] = upload(client, "invoice_1010.txt")
    record_review(held, "approve", "Dana", RATIONALE)  # claimed, then the server "crashed" before resuming
    assert conn.execute("SELECT status FROM invoice_runs WHERE id = ?", (held,)).fetchone()[0] == "Resuming"
    with open_client() as client:
        wait_idle(client)
        [row] = client.get("/api/payment-queue").json()["rows"]
        assert row["run_id"] == held and row["approved_by"] == "Dana"


def test_crash_mid_batch(conn, bank):
    with open_client() as client:
        upload(client, "invoice_1001.txt", "invoice_1006.csv", "invoice_1015.csv")
    rows = conn.execute("SELECT * FROM payment_queue ORDER BY id").fetchall()
    assert len(rows) == 3
    # The server stopped mid-batch: all 3 rows paying, the first already in the payments ledger.
    conn.execute("INSERT INTO payment_batches (batch_id, trigger, released_by, started_at) "
                 "VALUES ('B-0001', 'pay_all', 'Dana', '2026-01-01T00:00:00+00:00')")
    conn.execute("UPDATE payment_queue SET status = 'paying', batch_id = 'B-0001'")
    conn.execute("INSERT INTO payments (idempotency_key, vendor, amount_usd, paid_at, batch_id, payment_id) "
                 "VALUES (?, ?, ?, '2026-01-01T00:00:01+00:00', 'B-0001', 'PAY-000001')",
                 (row_key(rows[0]), rows[0]["vendor"], rows[0]["amount_usd"]))
    conn.commit()
    with open_client() as client:
        queue = client.get("/api/payment-queue").json()["rows"]
        assert [r["id"] for r in queue] == [rows[1]["id"], rows[2]["id"]]
        assert all(r["status"] == "queued" for r in queue)
        statuses = dict(conn.execute("SELECT id, status FROM payment_queue").fetchall())
        assert statuses[rows[0]["id"]] == "paid"
        body = pay(client, "Dana")
        batch = conn.execute("SELECT * FROM payment_batches WHERE batch_id = ?", (body["batch_id"],)).fetchone()
        assert batch["count"] == 2 and len(bank) == 2
        assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 3
        assert client.get("/api/payments").json()["count"] == 3
