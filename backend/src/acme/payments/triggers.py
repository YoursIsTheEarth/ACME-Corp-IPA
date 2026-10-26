"""When a payment batch is due (F38). Pure functions: the caller passes `now`, the snapshot, and the timing.

    next_batch_time(now, timing)                            # for display; None when no end-of-day batch
    end_of_day_due(now, last_eod_run, timing)               # once per day at the admin end-of-day time
    idle_batch_due(now, runs_snapshot, queue_count, batch_running, settings, timing)

`timing` is the admin `PaymentTiming` (`acme.admin.load_payment_timing`). End-of-day batches need delay
and pay at end of day on; idle batches need delay and pay when the Invoice Queue is empty on.
`load_runs_snapshot(conn)` and `payable_count(conn)` read the inputs for `idle_batch_due` from `acme.db`.
No scheduler lives here (add-backend-api wires APScheduler).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from acme.settings import Settings

if TYPE_CHECKING:
    from acme.admin import PaymentTiming

PROCESSING_STAGES = frozenset({"Uploaded", "Extracting", "Validating", "Deciding"})
PROCESSING_STATUSES = PROCESSING_STAGES | {"Resuming"}


@dataclass(frozen=True)
class RunActivity:
    """One invoice run as the idle trigger sees it."""

    stage: str | None
    status: str | None = None
    last_activity_at: datetime | None = None  # last time the run changed (aware datetime)

    @property
    def processing(self) -> bool:
        return self.stage in PROCESSING_STAGES or self.status in PROCESSING_STATUSES


def _batch_today(now: datetime, timing: PaymentTiming) -> datetime:
    local = now.astimezone(timing.tz)
    return datetime.combine(local.date(), timing.batch_time, tzinfo=local.tzinfo)


def next_batch_time(now: datetime, timing: PaymentTiming) -> datetime | None:
    """The next end-of-day batch time in the admin timezone (today if not yet passed, else tomorrow).

    None when no end-of-day batch is scheduled (delay off, or pay at end of day off).
    """
    if not timing.end_of_day_on:
        return None
    today = _batch_today(now, timing)
    if now < today:
        return today
    local = now.astimezone(timing.tz)
    return datetime.combine(local.date() + timedelta(days=1), timing.batch_time, tzinfo=local.tzinfo)


def end_of_day_due(now: datetime, last_eod_run: datetime | None, timing: PaymentTiming) -> bool:
    """True once per local day, at or after the end-of-day time, if today's batch hasn't run yet.

    Never due unless delay and pay at end of day are on.
    """
    if not timing.end_of_day_on:
        return False
    today = _batch_today(now, timing)
    return now >= today and (last_eod_run is None or last_eod_run < today)


def idle_batch_due(
    now: datetime,
    runs_snapshot: Iterable[RunActivity],
    queue_count: int,
    batch_running: bool,
    settings: Settings,
    timing: PaymentTiming,
) -> bool:
    """Delay and pay-when-queue-empty on, rows payable, no batch running, and nothing processing for
    `PAYMENT_IDLE_DELAY_S`.

    Runs Awaiting review (or resolved) never block; only their last change counts toward the delay.
    """
    if not timing.idle_on or queue_count <= 0 or batch_running:
        return False
    runs = list(runs_snapshot)
    if any(run.processing for run in runs):
        return False
    last = max((run.last_activity_at for run in runs if run.last_activity_at is not None), default=None)
    return last is None or now - last >= timedelta(seconds=settings.payment_idle_delay_s)


def load_runs_snapshot(conn: sqlite3.Connection) -> list[RunActivity]:
    """Every run's stage and status, with its latest `audit_log` time (else completed or uploaded time)."""
    rows = conn.execute(
        "SELECT r.stage, r.status, COALESCE((SELECT MAX(a.ts) FROM audit_log a WHERE a.run_id = r.id), "
        "r.completed_at, r.uploaded_at) AS last_ts FROM invoice_runs r"
    ).fetchall()
    return [RunActivity(r["stage"], r["status"], _aware(r["last_ts"])) for r in rows]


def _aware(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def payable_count(conn: sqlite3.Connection, max_attempts: int) -> int:
    """Rows a batch would pick: queued, or failed with attempts remaining."""
    return conn.execute(
        "SELECT COUNT(*) FROM payment_queue WHERE status = 'queued' OR (status = 'failed' AND attempts < ?)",
        (max_attempts,),
    ).fetchone()[0]
