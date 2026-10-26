"""Payment queue (F40), batch execution (F16, F38), payments and batch history (F26), payments CSV (F35)."""

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from acme import payments
from acme.api import queries
from acme.api.csv_export import csv_response
from acme.api.deps import db, services
from acme.api.schemas import ExecuteRequest

router = APIRouter(tags=["payments"])

PAYMENTS_CSV_COLUMNS = ("payment_id", "invoice_number", "revision", "vendor", "amount_usd", "original_amount",
                        "original_currency", "kind", "delta_label", "approved_by", "paid_at", "idempotency_key",
                        "batch_id", "batch_trigger", "released_by")


@router.get("/api/payments")
def list_payments(date_from: date | None = None, date_to: date | None = None,
                  vendor: str | None = None) -> dict[str, Any]:
    """Paid invoices filtered by paid date (admin end-of-day timezone) and vendor (substring), with the filter's total."""
    with db() as conn:
        return queries.payments_view(conn, date_from, date_to, vendor)


@router.get("/api/payments.csv", response_class=StreamingResponse)
def export_payments(date_from: date | None = None, date_to: date | None = None,
                    vendor: str | None = None) -> StreamingResponse:
    with db() as conn:
        rows = queries.payments_view(conn, date_from, date_to, vendor)["rows"]
    return csv_response("payments.csv", PAYMENTS_CSV_COLUMNS, rows)


@router.get("/api/payment-batches")
def list_batches() -> dict[str, Any]:
    with db() as conn:
        rows = queries.batches_view(conn)
    return {"rows": rows, "count": len(rows), "server_time": queries.server_time()}


@router.get("/api/payment-queue")
def payment_queue() -> dict[str, Any]:
    """Rows queued, paying, or failed, with count, total, and the payment mode (delay, next end-of-day batch,
    pay when the Invoice Queue is empty) from the admin settings."""
    with db() as conn:
        return queries.payment_queue_view(conn)


@router.post("/api/payment-queue/execute", status_code=202)
async def execute_batch(body: ExecuteRequest, request: Request) -> dict[str, Any]:
    """Start a batch: no `ids` = Pay all, one id = Pay now, several = Pay selected.

    Returns 202 with the `batch_id` once the batch is recorded; rows are paid in the background.
    409 when a batch is already running. Ids that are not queued or failed are skipped.
    """
    if body.ids is None:
        trigger = "pay_all"
    else:
        trigger = "pay_now" if len(set(body.ids)) == 1 else "pay_selected"
    try:
        batch_id = await services(request).batches.start(trigger, body.released_by, body.ids)
    except payments.BatchAlreadyRunning as exc:
        raise HTTPException(409, {"message": "A payment batch is already running."}) from exc
    except payments.InvalidBatchRequest as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"batch_id": batch_id, "trigger": trigger, "released_by": body.released_by}
