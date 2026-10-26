"""FastAPI app factory: `uvicorn acme.api.app:create_app --factory`.

The lifespan prepares `acme.db`, runs restart recovery (design D8) before serving, then starts the
upload worker, the payment scheduler, and the bridge from workflow/payment events to SSE.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from acme import payments, workflow
from acme.api import queries
from acme.api.deps import Services
from acme.api.events import EventBus
from acme.api.routers import admin, events, invoices, payments as payment_routes, reviews, stats
from acme.api.scheduler import BatchRunner, PaymentScheduler
from acme.api.worker import Worker
from acme.db import connect, init_schema
from acme.db.seed import seed
from acme.llm import key_status, missing_key_message
from acme.settings import get_settings

log = logging.getLogger(__name__)


def _ensure_db() -> None:
    """Create missing tables; seed reference data into an empty inventory (fresh checkout), as the CLI does."""
    conn = connect()
    try:
        init_schema(conn)
        if conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0:
            seed(conn)
            log.info("database_seeded", extra={"data": {"reason": "inventory was empty"}})
    finally:
        conn.close()


def _resuming_runs() -> list[str]:
    conn = connect()
    try:
        return [r["id"] for r in conn.execute(
            "SELECT id FROM invoice_runs WHERE status = 'Resuming' ORDER BY uploaded_at, id")]
    finally:
        conn.close()


def recover(worker: Worker) -> dict[str, Any]:
    """Restart durability (F28): settle `paying` rows, re-submit claimed reviews, re-enqueue orphaned runs.

    Runs Awaiting review need nothing: their checkpoint is on disk and the review endpoint resumes it.
    Without an LLM key, orphaned runs are reset to Uploaded but wait for a restart with a key.
    """
    batch = payments.recover_interrupted_batch()
    resuming = _resuming_runs()
    for run_id in resuming:
        worker.submit("review", run_id)
    orphaned = workflow.recover_orphaned_runs()
    llm_configured = key_status().configured
    if llm_configured:
        for run_id in orphaned:
            worker.submit("process", run_id)
    summary = {"batch": batch, "resuming": resuming, "orphaned": orphaned, "llm_configured": llm_configured}
    log.info("api_recovered", extra={"data": summary})
    return summary


def _workflow_publisher(bus: EventBus):
    """`on_event` for the workflow: adds the run's current list row so clients can update in place."""
    def on_event(name: str, data: dict[str, Any]) -> None:
        conn = connect()
        try:
            row = queries.run_summary(conn, data["run_id"])
        finally:
            conn.close()
        bus.publish(name, {**data, "invoice": row})
    return on_event


def create_app(enable_scheduler: bool = True) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        status = key_status()  # an invalid provider stops startup; a missing key only blocks processing
        if not status.configured:
            log.warning("llm_not_configured", extra={"data": {
                "missing_key": status.missing_key, "message": missing_key_message(status.missing_key, status.provider)}})
        await asyncio.to_thread(_ensure_db)
        bus = EventBus()
        bus.bind(asyncio.get_running_loop())
        worker = Worker(_workflow_publisher(bus), get_settings().worker_concurrency)
        batches = BatchRunner()
        scheduler = PaymentScheduler(batches)
        app.state.services = Services(bus, worker, batches, scheduler)
        unsubscribe = payments.subscribe(bus.publish)
        await asyncio.to_thread(recover, worker)
        worker.start()
        if enable_scheduler:
            scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown()
            await worker.stop()
            await asyncio.to_thread(batches.shutdown)
            unsubscribe()

    app = FastAPI(title="ACME Corp IPA API", version="0.1.0", lifespan=lifespan,
                  description="Invoice Processing Automation: upload, review, and pay invoices.")
    app.add_middleware(CORSMiddleware, allow_origins=[settings.api_cors_origin], allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])
    for module in (invoices, reviews, payment_routes, stats, admin, events):
        app.include_router(module.router)
    return app
