"""Upload worker (design D2): an `asyncio.Queue` of jobs, run on a thread pool in arrival order.

Jobs are `("process", run_id)` (a new or recovered run through the graph) and `("review", run_id)`
(resume a claimed review). With `WORKER_CONCURRENCY=1` (the default) one consumer runs them in
order, which keeps duplicate and revision detection deterministic, like the CLI's sorted order.
"""

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from acme import workflow

log = logging.getLogger(__name__)

JobKind = Literal["process", "review"]
EventCallback = Callable[[str, dict[str, Any]], None]


class Worker:
    def __init__(self, on_event: EventCallback, concurrency: int = 1) -> None:
        self.on_event = on_event
        self.concurrency = max(1, concurrency)
        self.queue: asyncio.Queue[tuple[JobKind, str]] = asyncio.Queue()
        self.pool = ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="acme-worker")
        self._tasks: list[asyncio.Task] = []
        self._busy = 0

    def start(self) -> None:
        self._tasks = [asyncio.create_task(self._consume()) for _ in range(self.concurrency)]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        # A job already running finishes (it is a blocking graph call); queued jobs are recovered at startup.
        await asyncio.to_thread(self.pool.shutdown, wait=True, cancel_futures=True)

    def submit(self, kind: JobKind, run_id: str) -> None:
        self.queue.put_nowait((kind, run_id))

    @property
    def idle(self) -> bool:
        return self.queue.empty() and self._busy == 0

    def _run(self, kind: JobKind, run_id: str) -> None:
        if kind == "process":
            workflow.process_run(run_id, on_event=self.on_event)
        else:
            workflow.continue_review(run_id, on_event=self.on_event)

    async def _consume(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            kind, run_id = await self.queue.get()
            self._busy += 1
            try:
                await loop.run_in_executor(self.pool, self._run, kind, run_id)
            except Exception:  # process_run fails closed itself; this only guards the consumer
                log.exception("worker_job_failed", extra={"data": {"kind": kind, "run_id": run_id}})
            finally:
                self._busy -= 1
                self.queue.task_done()
