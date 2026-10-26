"""Structured JSON-lines logging plus the `audit_log` ledger.

    configure_logging()
    with run_context("r-123", agent="validation"):
        log.info("findings_written", extra={"data": {"count": 2}})
        audit("r-123", "validation", "findings_written", {"findings": [...]})

The log message is the event name; untrusted text belongs in `extra={"data": {...}}`,
which is emitted only as JSON values.
"""

import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Iterator

from pydantic import BaseModel

run_id_var: ContextVar[str | None] = ContextVar("acme_run_id", default=None)
agent_var: ContextVar[str | None] = ContextVar("acme_agent", default=None)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    return str(value)


def dumps(value: Any) -> str:
    """JSON-encode with Decimals as strings and dates as ISO 8601."""
    return json.dumps(value, default=_json_default, ensure_ascii=False)


@contextmanager
def run_context(run_id: str | None, agent: str | None = None) -> Iterator[None]:
    """Scope log lines (and LLM call records) to a run and, optionally, an agent."""
    run_token = run_id_var.set(run_id)
    agent_token = agent_var.set(agent) if agent is not None else None
    try:
        yield
    finally:
        if agent_token is not None:
            agent_var.reset(agent_token)
        run_id_var.reset(run_token)


@contextmanager
def agent_context(agent: str) -> Iterator[None]:
    token = agent_var.set(agent)
    try:
        yield
    finally:
        agent_var.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        if (run_id := run_id_var.get()) is not None:
            entry["run_id"] = run_id
        if (agent := agent_var.get()) is not None:
            entry["agent"] = agent
        data = getattr(record, "data", None)
        if data is not None:
            entry["data"] = data
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return dumps(entry)


def configure_logging(level: int | str = logging.INFO, stream=None) -> None:
    """Send all `acme` and root logs to one JSON-lines handler (stderr by default)."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        if isinstance(existing.formatter, JsonFormatter):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)


from acme.logging.audit import audit, read_trace  # noqa: E402

__all__ = [
    "JsonFormatter",
    "agent_context",
    "agent_var",
    "audit",
    "configure_logging",
    "dumps",
    "read_trace",
    "run_context",
    "run_id_var",
]
