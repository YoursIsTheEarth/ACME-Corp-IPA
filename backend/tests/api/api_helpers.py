"""Helpers shared by the API tests."""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from fastapi.testclient import TestClient

from acme.api.app import create_app
from workflow_helpers import INVOICES

TIMEOUT_S = 60


@contextmanager
def open_client(enable_scheduler: bool = False) -> Iterator[TestClient]:
    with TestClient(create_app(enable_scheduler=enable_scheduler)) as client:
        yield client


def wait_for(predicate: Callable[[], object], timeout: float = TIMEOUT_S, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")


def wait_idle(client: TestClient) -> None:
    """Until the worker queue is drained and no batch is running."""
    svc = client.app.state.services
    wait_for(lambda: svc.worker.idle and svc.batches.idle)


def file_part(path: Path | str, name: str | None = None):
    path = Path(path) if Path(path).is_absolute() else INVOICES / path
    return ("files", (name or path.name, path.read_bytes()))


def upload(client: TestClient, *files, wait: bool = True) -> list[str]:
    """Upload files (names under data/invoices or paths) in one request; returns the run ids in order."""
    response = client.post("/api/invoices", files=[file_part(f) for f in files])
    assert response.status_code == 202, response.text
    ids = [entry["id"] for entry in response.json()["files"]]
    if wait:
        wait_idle(client)
    return ids


def run(client: TestClient, run_id: str) -> dict:
    return client.get(f"/api/invoices/{run_id}").json()


def pay(client: TestClient, released_by: str = "Dana", ids=None, wait: bool = True) -> dict:
    body = {"released_by": released_by} | ({"ids": ids} if ids is not None else {})
    response = client.post("/api/payment-queue/execute", json=body)
    assert response.status_code == 202, response.text
    if wait:
        wait_idle(client)
    return response.json()


@contextmanager
def live_server(enable_scheduler: bool = False) -> Iterator[str]:
    """A real uvicorn server on a free port (TestClient cannot consume an endless SSE stream)."""
    config = uvicorn.Config(create_app(enable_scheduler=enable_scheduler), host="127.0.0.1", port=0,
                            log_level="warning", timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_for(lambda: server.started, timeout=20)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=20)
