"""In-process event bus for `GET /api/events` (design D7).

One `asyncio.Queue` per connected client; `publish` fans out to all of them and is safe to call
from worker threads (it hops onto the loop with `call_soon_threadsafe`). Events are not replayed:
clients re-fetch the list endpoints on reconnect.
"""

import asyncio
import dataclasses
import json
import logging
from typing import Any

from acme.logging import dumps

log = logging.getLogger(__name__)

QUEUE_SIZE = 1000


def _plain(value: Any) -> Any:
    """JSON-ready copy of an event payload (dataclasses such as `RowResult` included)."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


class EventBus:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set[asyncio.Queue] = set()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(QUEUE_SIZE)
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._clients.discard(queue)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def publish(self, name: str, data: dict[str, Any]) -> None:
        """Send `name` with `data` to every client. Callable from any thread."""
        if self._loop is None or self._loop.is_closed():
            return
        message = {"event": name, "data": json.loads(dumps(_plain(data)))}
        if self._on_loop_thread():
            self._fan_out(message)
        else:
            try:
                self._loop.call_soon_threadsafe(self._fan_out, message)
            except RuntimeError:  # loop closed during shutdown
                pass

    def _on_loop_thread(self) -> bool:
        try:
            return asyncio.get_running_loop() is self._loop
        except RuntimeError:
            return False

    def _fan_out(self, message: dict[str, Any]) -> None:
        for queue in list(self._clients):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:  # a stalled client misses events; it re-fetches on reconnect
                log.warning("sse_client_queue_full")
