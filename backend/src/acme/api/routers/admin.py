"""Admin settings (F41): payment timing, read and saved without an LLM key."""

import asyncio
from typing import Any

from fastapi import APIRouter, Request

from acme.admin import PaymentTiming, admin_settings, load_payment_timing, save_payment_timing
from acme.api.deps import db, services
from acme.api.schemas import AdminSettingsRequest

router = APIRouter(tags=["admin"])


@router.get("/api/admin/settings")
def get_admin_settings() -> dict[str, Any]:
    """`delay_payments, pay_at_end_of_day, end_of_day_time, end_of_day_timezone, pay_when_queue_empty`, plus
    `updated_by` and `updated_at` of the last save (null if never saved). Unsaved values are the defaults."""
    with db() as conn:
        return admin_settings(conn)


@router.put("/api/admin/settings")
async def put_admin_settings(body: AdminSettingsRequest, request: Request) -> dict[str, Any]:
    """Save all five settings (audited, `settings.updated` sent) and apply them without a restart.

    422 when `updated_by` is blank or over 50 characters after trimming, `end_of_day_time` is not HH:MM, or
    `end_of_day_timezone` is not a known IANA name; nothing is saved then. Turning delay off pays everything
    then payable in one `immediate` batch on the batch runner.
    """
    timing = PaymentTiming(**body.model_dump(exclude={"updated_by"}))
    before = await asyncio.to_thread(load_payment_timing)
    saved = await asyncio.to_thread(lambda: save_payment_timing(timing, body.updated_by, pay_queued=False))
    scheduler = services(request).scheduler
    scheduler.reschedule(timing)
    if before.delay_payments and not timing.delay_payments:
        await scheduler.idle_tick()  # delay now off: an `immediate` batch when rows are payable
    return saved
