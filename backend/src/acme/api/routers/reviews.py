"""Human review resume (F17, F25, F28): `POST /api/invoices/{id}/review`."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from acme import workflow
from acme.api import queries
from acme.api.deps import db, services
from acme.api.schemas import ReviewRequest

router = APIRouter(tags=["reviews"])


@router.post("/api/invoices/{run_id}/review")
async def review_invoice(run_id: str, body: ReviewRequest, request: Request) -> dict[str, Any]:
    """Record the decision (claim `Awaiting review -> Resuming`), then resume the run on the worker.

    422: bad decision, reviewer name (1-50 after trimming), or rationale (< 15 characters).
    409: the invoice is not awaiting review (already decided or still processing).
    For a credit hold, approve = Credit confirmed and reject = Reject revision; neither pays.
    """
    with db() as conn:
        if queries.run_exists(conn, run_id) is None:
            raise HTTPException(404, f"Invoice {run_id} not found")
    try:
        await asyncio.to_thread(workflow.record_review, run_id, body.decision, body.reviewer, body.rationale)
    except workflow.ReviewConflict as exc:
        raise HTTPException(409, {"message": "This invoice is no longer awaiting review.",
                                  "status": exc.status}) from exc
    except workflow.ReviewInputError as exc:
        raise HTTPException(422, str(exc)) from exc
    svc = services(request)
    svc.worker.on_event("invoice.stage_changed", {"run_id": run_id, "stage": "Awaiting review", "status": "Resuming"})
    svc.worker.submit("review", run_id)
    return {"id": run_id, "decision": body.decision, "reviewer": body.reviewer, "status": "Resuming"}
