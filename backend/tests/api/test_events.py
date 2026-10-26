"""SSE stream, payment events, and the P1 stats figures (tasks 7.1-7.3), against a real uvicorn server."""

import json
import threading
from contextlib import contextmanager

import httpx

from acme.api.routers.events import PING_S
from api_helpers import INVOICES, live_server, wait_for

SEVEN = ("invoice_1001.txt", "invoice_1004.json", "invoice_1004_revised.json", "invoice_1006.csv",
         "invoice_1011.pdf", "invoice_1012.pdf", "invoice_1014.xml", "invoice_1015.csv")


@contextmanager
def sse(base: str):
    """Collect `(event, data)` pairs from /api/events in a background thread."""
    received: list[tuple[str, dict]] = []
    stop = threading.Event()

    def listen():
        try:
            read(base)
        except httpx.HTTPError:  # the server shut down with the stream open
            pass

    def read(base):
        with httpx.Client(timeout=None) as http, http.stream("GET", f"{base}/api/events") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            name = None
            for line in response.iter_lines():
                if stop.is_set():
                    return
                if line.startswith("event:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and name:
                    received.append((name, json.loads(line.split(":", 1)[1].strip())))
                    name = None

    thread = threading.Thread(target=listen, daemon=True)
    thread.start()
    wait_for(lambda: any(name == "ready" for name, _ in received), timeout=20)
    try:
        yield received
    finally:
        stop.set()


def post_files(http: httpx.Client, base: str, *names: str) -> list[str]:
    files = [("files", (n, (INVOICES / n).read_bytes())) for n in names]
    response = http.post(f"{base}/api/invoices", files=files)
    assert response.status_code == 202
    return [f["id"] for f in response.json()["files"]]


def test_ping_interval():
    assert PING_S <= 15


def test_invoice_events_in_order():
    with live_server() as base, sse(base) as received, httpx.Client() as http:
        [run_id] = post_files(http, base, "invoice_1002.txt")
        wait_for(lambda: any(n == "invoice.resolved" for n, _ in received))
        mine = [(n, d) for n, d in received if d.get("run_id") == run_id]
        names = [n for n, _ in mine]
        assert names[0] == "invoice.created" and names[-1] == "invoice.resolved"
        assert set(names[1:-1]) == {"invoice.stage_changed"} and len(names) >= 3
        assert [d["stage"] for n, d in mine if n == "invoice.stage_changed"][:3] == ["Extracting", "Validating", "Deciding"]
        resolved = mine[-1][1]
        assert resolved["final_status"] == "Rejected" and resolved["invoice"]["final_status"] == "Rejected"
        assert resolved["invoice"]["invoice_number"] == "INV-1002"


def test_every_client_gets_every_event():
    with live_server() as base, sse(base) as first, sse(base) as second, httpx.Client() as http:
        [run_id] = post_files(http, base, "invoice_1002.txt")
        for received in (first, second):
            wait_for(lambda: any(n == "invoice.resolved" and d["run_id"] == run_id for n, d in received))


def test_settings_updated_event_carries_the_full_settings():
    body = {"delay_payments": True, "pay_at_end_of_day": True, "end_of_day_time": "15:00",
            "end_of_day_timezone": "America/New_York", "pay_when_queue_empty": False, "updated_by": "Dana"}
    with live_server() as base, sse(base) as first, sse(base) as second, httpx.Client() as http:
        saved = http.put(f"{base}/api/admin/settings", json=body).json()
        for received in (first, second):
            wait_for(lambda: any(n == "settings.updated" for n, _ in received))
            [data] = [d for n, d in received if n == "settings.updated"]
            assert data == saved and data["updated_by"] == "Dana" and data["updated_at"]
            assert {k: data[k] for k in body} == body


def test_revision_swap_and_batch_events():
    with live_server() as base, sse(base) as received, httpx.Client() as http:
        ids = dict(zip(SEVEN, post_files(http, base, *SEVEN)))
        wait_for(lambda: http.get(f"{base}/api/stats").json()["processing"] == 0
                 and http.get(f"{base}/api/payment-queue").json()["count"] == 7)
        cancelled = [d for n, d in received if n == "payment.cancelled"]
        assert [d["run_id"] for d in cancelled] == [ids["invoice_1004.json"]]
        queued = [d for n, d in received if n == "payment.queued"]
        swap = [d for d in queued if d["run_id"] == ids["invoice_1004_revised.json"]]
        assert [(d["kind"], d["amount_usd"]) for d in swap] == [("replacement", "5940.00")]
        assert received.index(("payment.cancelled", cancelled[0])) < received.index(("payment.queued", swap[0]))

        response = http.post(f"{base}/api/payment-queue/execute", json={"released_by": "Dana"})
        assert response.status_code == 202
        batch_id = response.json()["batch_id"]
        wait_for(lambda: any(n == "batch.finished" for n, _ in received))
        batch = [(n, d) for n, d in received if n.startswith(("batch.", "payment.created"))]
        names = [n for n, _ in batch]
        assert names == ["batch.started", *["payment.created"] * 7, "batch.finished"]
        assert all(d["batch_id"] == batch_id for _, d in batch)
        finished = batch[-1][1]
        assert (finished["count"], finished["total_usd"], finished["failed_count"]) == (7, "37620.00", 0)
        assert len(finished["results"]) == 7 and finished["results"][0]["status"] == "paid"


def test_p1_stats_after_golden_run(api_golden):
    stats = api_golden["stats"]
    assert stats["duplicates_caught"] == 3
    assert stats["dollars_paid"] == "37620.00" and stats["dollars_queued"] == "0.00"
    assert stats["paid_today"] == 7 and stats["rejected_today"] == 11 and stats["awaiting_review"] == 1
    assert float(stats["dollars_blocked"]) > 0
