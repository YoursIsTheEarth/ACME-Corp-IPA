"""Append-only `audit_log` writer and run trace reader."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from acme.db import connect
from acme.logging import dumps


def audit(
    run_id: str | None,
    agent: str | None,
    event: str,
    payload: Any = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Append one audit row. Uses `conn` if given, else a short-lived connection."""
    row = (
        run_id,
        datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        agent,
        event,
        dumps({} if payload is None else payload),
    )
    own = conn is None
    conn = conn or connect()
    try:
        conn.execute(
            "INSERT INTO audit_log (run_id, ts, agent, event, payload_json) VALUES (?, ?, ?, ?, ?)",
            row,
        )
        conn.commit()
    finally:
        if own:
            conn.close()


def read_trace(run_id: str, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """Return a run's audit rows in the order they happened, payloads decoded."""
    own = conn is None
    conn = conn or connect()
    try:
        rows = conn.execute(
            "SELECT run_id, ts, agent, event, payload_json FROM audit_log "
            "WHERE run_id = ? ORDER BY ts, id",
            (run_id,),
        ).fetchall()
    finally:
        if own:
            conn.close()
    return [
        {"run_id": r["run_id"], "ts": r["ts"], "agent": r["agent"], "event": r["event"],
         "payload": json.loads(r["payload_json"])}
        for r in rows
    ]
