"""Shared request dependencies: the app's services and a short-lived `acme.db` connection."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import Request

from acme.api.events import EventBus
from acme.api.scheduler import BatchRunner, PaymentScheduler
from acme.api.worker import Worker
from acme.db import connect


@dataclass
class Services:
    bus: EventBus
    worker: Worker
    batches: BatchRunner
    scheduler: PaymentScheduler


def services(request: Request) -> Services:
    return request.app.state.services


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """Open inside the endpoint body: sqlite connections stay on the thread that opened them."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
