"""In-process listeners for payment events (the API forwards them to SSE).

    unsubscribe = subscribe(lambda name, data: ...)

Events: `payment.queued`, `payment.cancelled`, `batch.started`, `payment.created`, `batch.finished`, and
`settings.updated` (emitted by `acme.admin` when payment timing is saved).
A failing listener is logged and never breaks a payment path.
"""

import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

Listener = Callable[[str, dict[str, Any]], None]
_listeners: list[Listener] = []


def subscribe(listener: Listener) -> Callable[[], None]:
    _listeners.append(listener)
    return lambda: _listeners.remove(listener) if listener in _listeners else None


def emit(name: str, data: dict[str, Any]) -> None:
    for listener in list(_listeners):
        try:
            listener(name, data)
        except Exception:
            log.exception("payment_event_listener_failed", extra={"data": {"event": name}})
