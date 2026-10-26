"""Server-Sent Events stream (F29): every event goes to every connected client; ping every 15 seconds."""

import json

from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse

from acme.api import queries
from acme.api.deps import services

router = APIRouter(tags=["events"])

PING_S = 15


@router.get("/api/events", response_class=EventSourceResponse)
async def event_stream(request: Request) -> EventSourceResponse:
    """Events: invoice.created, invoice.stage_changed, invoice.resolved, payment.queued, payment.cancelled,
    batch.started, payment.created, batch.finished. A `ready` event is sent first. No replay: re-fetch
    the list endpoints after reconnecting."""
    bus = services(request).bus
    queue = bus.subscribe()

    async def messages():
        try:
            yield {"event": "ready", "data": json.dumps({"server_time": queries.server_time()})}
            while True:
                message = await queue.get()
                yield {"event": message["event"], "data": json.dumps(message["data"])}
        finally:
            bus.unsubscribe(queue)

    return EventSourceResponse(messages(), ping=PING_S)
