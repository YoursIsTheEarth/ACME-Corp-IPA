"""Admin settings (F41): payment timing kept in `admin_settings`, with the spec defaults in code.

    timing = load_payment_timing()                  # stored keys merged over the defaults
    view = admin_settings()                         # the timing plus updated_by / updated_at of the last save
    save_payment_timing(timing, "Dana")             # validate, write, audit, emit `settings.updated`

A saved change applies to the next decision without a restart: every reader loads the timing again.
"""

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, field_validator

from acme.db import connect
from acme.logging import dumps
from acme.payments import events, pay_now_if_immediate
from acme.payments._store import immediate, utcnow

AGENT = "admin"
NAME_MAX = 50
TIME_PATTERN = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


class PaymentTiming(BaseModel):
    """Payment timing with the spec defaults: delay on, end of day off (17:00 Central when on), queue-empty on."""

    delay_payments: bool = True
    pay_at_end_of_day: bool = False
    end_of_day_time: str = "17:00"
    end_of_day_timezone: str = "America/Chicago"
    pay_when_queue_empty: bool = True

    @field_validator("end_of_day_time")
    @classmethod
    def _hh_mm(cls, value: str) -> str:
        if not TIME_PATTERN.fullmatch(value):
            raise ValueError(f"end_of_day_time must be a 24-hour HH:MM time, got {value!r}")
        return value

    @field_validator("end_of_day_timezone")
    @classmethod
    def _iana(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone {value!r}; use an IANA name such as America/Chicago") from None
        return value

    @property
    def batch_time(self) -> time:
        return time.fromisoformat(self.end_of_day_time)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.end_of_day_timezone)

    @property
    def end_of_day_on(self) -> bool:
        """An `end_of_day` batch is scheduled: delay and pay at end of day are both on."""
        return self.delay_payments and self.pay_at_end_of_day

    @property
    def idle_on(self) -> bool:
        """An `idle` batch may run: delay and pay when the Invoice Queue is empty are both on."""
        return self.delay_payments and self.pay_when_queue_empty


KEYS = tuple(PaymentTiming.model_fields)


def validate_name(name: str | None) -> str:
    """The saver's name trimmed; 1 to 50 characters, the same rule as reviewers and releasers."""
    value = (name or "").strip()
    if not 1 <= len(value) <= NAME_MAX:
        raise ValueError(f"updated_by must be 1 to {NAME_MAX} characters after trimming")
    return value


@contextmanager
def _connection(conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    if conn is not None:
        yield conn
        return
    own = connect()
    try:
        yield own
    finally:
        own.close()


def load_payment_timing(conn: sqlite3.Connection | None = None) -> PaymentTiming:
    """Stored payment timing merged over the defaults (a key never saved keeps its default)."""
    with _connection(conn) as c:
        rows = c.execute(f"SELECT key, value FROM admin_settings WHERE key IN ({','.join('?' * len(KEYS))})",
                         KEYS).fetchall()
    return PaymentTiming(**{r["key"]: json.loads(r["value"]) for r in rows})


def admin_settings(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """The payment timing plus who saved it last and when (both None if never saved)."""
    with _connection(conn) as c:
        timing = load_payment_timing(c)
        last = c.execute("SELECT updated_by, updated_at FROM admin_settings ORDER BY updated_at DESC LIMIT 1").fetchone()
    return timing.model_dump() | {"updated_by": last["updated_by"] if last else None,
                                  "updated_at": last["updated_at"] if last else None}


def save_payment_timing(timing: PaymentTiming | dict[str, Any], updated_by: str,
                        conn: sqlite3.Connection | None = None, pay_queued: bool = True) -> dict[str, Any]:
    """Validate and save all five keys plus one `settings.updated` audit entry in one transaction.

    Emits `settings.updated` with the saved settings. When delay changes from on to off and `pay_queued`
    is true, pays everything then payable in one `immediate` batch (the API passes False and starts that
    batch on its own runner). Raises ValueError (pydantic's ValidationError included) on bad input,
    saving nothing. Returns `admin_settings()`.
    """
    timing = PaymentTiming.model_validate(timing.model_dump() if isinstance(timing, PaymentTiming) else timing)
    name = validate_name(updated_by)
    with _connection(conn) as c:
        old = load_payment_timing(c)
        now = utcnow()
        new_values, old_values = timing.model_dump(), old.model_dump()
        changes = {k: [old_values[k], new_values[k]] for k in KEYS if old_values[k] != new_values[k]}
        with immediate(c):
            c.executemany(
                "INSERT INTO admin_settings (key, value, updated_by, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by, "
                "updated_at = excluded.updated_at",
                [(k, json.dumps(new_values[k]), name, now) for k in KEYS])
            c.execute("INSERT INTO audit_log (run_id, ts, agent, event, payload_json) VALUES (NULL, ?, ?, ?, ?)",
                      (now, AGENT, "settings.updated", dumps({"by": name, "changes": changes})))
        view = admin_settings(c)
    events.emit("settings.updated", view)
    if pay_queued and old.delay_payments and not timing.delay_payments:
        pay_now_if_immediate()
    return view
