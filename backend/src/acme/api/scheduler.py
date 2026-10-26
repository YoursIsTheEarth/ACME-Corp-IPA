"""Payment batches off the request path (design D5, D6).

`BatchRunner.start` runs `acme.payments.run_batch` on its own thread pool and returns the batch ID as
soon as the batch is recorded; the rows are paid in the background. `PaymentScheduler` adds the
APScheduler jobs from the admin payment timing: the `end_of_day` cron at the admin time and timezone
(only while delay and pay at end of day are on; `reschedule` replaces or removes it on save) and a
5-second check that reads the timing every tick: delay on -> `idle` batch when `idle_batch_due`, delay
off -> `immediate` batch when rows are payable. Both skip a tick while a batch runs.
"""

import asyncio
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from acme import payments
from acme.admin import PaymentTiming, load_payment_timing
from acme.db import connect
from acme.settings import get_settings

log = logging.getLogger(__name__)

IDLE_CHECK_S = 5


class BatchRunner:
    def __init__(self) -> None:
        # More than one thread, so a second request reaches the batch lock (409) instead of waiting.
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="acme-batch")
        self._futures: set[Future] = set()

    async def start(self, trigger: str, released_by: str | None = None, ids: list[int] | None = None) -> str:
        """Start a batch; return its ID once recorded. Raises BatchAlreadyRunning or InvalidBatchRequest."""
        loop = asyncio.get_running_loop()
        started: asyncio.Future[str] = loop.create_future()

        def mark_started(batch_id: str) -> None:
            if not started.done():
                started.set_result(batch_id)

        def run() -> payments.BatchResult:
            thread = threading.get_ident()

            def listener(name, data):
                if name == "batch.started" and threading.get_ident() == thread:
                    loop.call_soon_threadsafe(mark_started, data["batch_id"])

            unsubscribe = payments.subscribe(listener)
            try:
                return payments.run_batch(trigger, released_by, ids)
            finally:
                unsubscribe()

        future = self.pool.submit(run)
        self._futures.add(future)
        future.add_done_callback(self._done)
        batch = asyncio.wrap_future(future)
        await asyncio.wait({started, batch}, return_when=asyncio.FIRST_COMPLETED)
        if started.done():
            return started.result()
        started.cancel()
        return batch.result().batch_id  # raises the batch's exception; else it finished before the callback ran

    def _done(self, future: Future) -> None:
        self._futures.discard(future)
        if not future.cancelled() and (exc := future.exception()) is not None and not isinstance(
                exc, (payments.BatchAlreadyRunning, payments.InvalidBatchRequest)):
            log.error("payment_batch_failed", exc_info=exc)

    @property
    def idle(self) -> bool:
        return not self._futures

    def shutdown(self) -> None:
        self.pool.shutdown(wait=True)


class PaymentScheduler:
    def __init__(self, runner: BatchRunner) -> None:
        self.runner = runner
        self.scheduler: AsyncIOScheduler | None = None
        self.timing: PaymentTiming | None = None  # the timing the jobs were built from

    def start(self) -> None:
        utc = ZoneInfo("UTC")
        self.scheduler = AsyncIOScheduler(timezone=utc)
        self.scheduler.add_job(self.idle_tick, IntervalTrigger(seconds=IDLE_CHECK_S, timezone=utc), id="idle_check",
                               coalesce=True, max_instances=1)
        self.scheduler.start()
        self.reschedule(load_payment_timing())

    def reschedule(self, timing: PaymentTiming) -> None:
        """Replace the `end_of_day` cron job for `timing`, or remove it when no end-of-day batch is scheduled."""
        self.timing = timing
        if self.scheduler is None:
            return
        if timing.end_of_day_on:
            at = timing.batch_time
            self.scheduler.add_job(self.end_of_day, CronTrigger(hour=at.hour, minute=at.minute, timezone=timing.tz),
                                   id="end_of_day", replace_existing=True, coalesce=True, max_instances=1,
                                   misfire_grace_time=300)
        elif self.scheduler.get_job("end_of_day") is not None:
            self.scheduler.remove_job("end_of_day")

    def shutdown(self) -> None:
        if self.scheduler is not None and self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def end_of_day(self) -> str | None:
        if not (await asyncio.to_thread(load_payment_timing)).end_of_day_on:
            return None
        return await self._try("end_of_day")

    async def idle_tick(self, now: datetime | None = None) -> str | None:
        """One check with the timing read now: an `immediate` batch (delay off, rows payable) or an `idle`
        batch (`idle_batch_due`). Picks up a timing saved elsewhere (CLI). Returns the batch ID or None."""
        now = now or datetime.now(timezone.utc)
        timing, trigger = await asyncio.to_thread(self._due, now)
        if timing != self.timing:
            self.reschedule(timing)
        if trigger is None:
            return None
        return await self._try(trigger)

    @staticmethod
    def _due(now: datetime) -> tuple[PaymentTiming, str | None]:
        settings = get_settings()
        conn = connect()
        try:
            timing = load_payment_timing(conn)
            if not timing.delay_payments:
                due = not payments.is_batch_running() and bool(
                    payments.immediate_scope(conn, settings.payment_max_attempts))
                return timing, "immediate" if due else None
            if not timing.idle_on:
                return timing, None
            snapshot = payments.load_runs_snapshot(conn)
            count = payments.payable_count(conn, settings.payment_max_attempts)
        finally:
            conn.close()
        due = payments.idle_batch_due(now, snapshot, count, payments.is_batch_running(), settings, timing)
        return timing, "idle" if due else None

    async def _try(self, trigger: str) -> str | None:
        try:
            return await self.runner.start(trigger)
        except payments.BatchAlreadyRunning:
            log.info("scheduled_batch_skipped", extra={"data": {"trigger": trigger}})
            return None
