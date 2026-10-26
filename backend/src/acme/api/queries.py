"""Read-only views over `acme.db` for the list, detail, payment, and stats endpoints.

Every function returns the full current state (the polling contract, F29) as JSON-ready dicts:
money is a 2-decimal string, timestamps are ISO 8601 (UTC unless noted). Writes never happen here;
the routers call `acme.workflow` and `acme.payments` for those.
"""

import json
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from acme import payments, workflow
from acme.admin import load_payment_timing
from acme.llm import active_models, key_status
from acme.logging import read_trace
from acme.payments._store import row_key
from acme.payments.revisions import money
from acme.settings import get_settings

PROCESSING_STAGES = ("Uploaded", "Extracting", "Validating", "Deciding")
QUEUE_STAGES = (*PROCESSING_STAGES, "Awaiting review")
OPEN_PAYMENT_STATUSES = ("queued", "paying", "failed")
REJECTED_STATUSES = ("Rejected", "Duplicate")
SEVERITY_RANK = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
KEY_FINDINGS = 3
FINDING_EVENTS = ("validation.findings", "validation.fallback", "rejection.recorded", "invoice.superseded",
                  "extraction_attempt")
TRIGGER_LABELS = {"end_of_day": "End of day", "idle": "Invoice Queue idle", "immediate": "Immediate (at approval)",
                  "pay_all": "Pay all", "pay_selected": "Pay selected", "pay_now": "Pay now"}
CONTENT_TYPES = {".pdf": "application/pdf", ".txt": "text/plain", ".csv": "text/csv",
                 ".json": "application/json", ".xml": "application/xml", ".eml": "message/rfc822"}


# --- helpers ---------------------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def server_time() -> str:
    return now_utc().isoformat(timespec="seconds")


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    value = datetime.fromisoformat(ts)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _local_date(ts: str | None, tz: ZoneInfo) -> date | None:
    """The calendar day of `ts` in `tz` (the admin end-of-day timezone, finance's business day)."""
    value = _parse(ts)
    return value.astimezone(tz).date() if value else None


def _seconds(start: str | None, end: datetime | None) -> int | None:
    begin = _parse(start)
    return None if begin is None or end is None else max(0, int((end - begin).total_seconds()))


def _money(value: Any) -> str | None:
    return None if value in (None, "") else str(money(value))


def _sum(values) -> str:
    return str(money(sum((Decimal(v) for v in values if v not in (None, "")), Decimal("0"))))


def _marks(values) -> str:
    return ",".join("?" * len(values))


def file_format(file_name: str) -> str:
    return Path(file_name).suffix.lower().lstrip(".")


def content_type(file_name: str) -> str:
    return CONTENT_TYPES.get(Path(file_name).suffix.lower(), "application/octet-stream")


def _matches(text: str | None, needle: str | None) -> bool:
    return not needle or needle.casefold() in (text or "").casefold()


def _in_range(day: date | None, date_from: date | None, date_to: date | None) -> bool:
    if date_from is None and date_to is None:
        return True
    return day is not None and (date_from is None or day >= date_from) and (date_to is None or day <= date_to)


# --- per-run facts from the audit ledger ------------------------------------------------------

def _run_facts(conn: sqlite3.Connection, run_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Findings, last activity, and extraction retries per run, read from `audit_log` in two queries."""
    facts: dict[str, dict[str, Any]] = {rid: {"validation": [], "rejection": [], "superseded": [],
                                              "failed_attempts": 0, "last_ts": None} for rid in run_ids}
    if not run_ids:
        return facts
    for row in conn.execute(f"SELECT run_id, MAX(ts) AS ts FROM audit_log WHERE run_id IN ({_marks(run_ids)}) "
                            "GROUP BY run_id", run_ids):
        facts[row["run_id"]]["last_ts"] = row["ts"]
    rows = conn.execute(
        f"SELECT run_id, event, payload_json FROM audit_log WHERE run_id IN ({_marks(run_ids)}) "
        f"AND event IN ({_marks(FINDING_EVENTS)}) ORDER BY ts, id", (*run_ids, *FINDING_EVENTS))
    for row in rows:
        fact, payload = facts[row["run_id"]], json.loads(row["payload_json"])
        if row["event"] in ("validation.findings", "validation.fallback"):
            fact["validation"] = payload.get("findings") or []
        elif row["event"] == "rejection.recorded" and payload.get("findings"):
            fact["rejection"] = payload["findings"]
        elif row["event"] == "invoice.superseded" and payload.get("finding"):
            fact["superseded"].append(payload["finding"])
        elif row["event"] == "extraction_attempt" and payload.get("outcome") != "accepted":
            fact["failed_attempts"] += 1
    return facts


def _finding(raw: dict[str, Any]) -> dict[str, Any]:
    return {"code": raw.get("code"), "severity": raw.get("severity"), "message": raw.get("message"),
            "evidence": raw.get("evidence") or {}}


def _findings(fact: dict[str, Any]) -> list[dict[str, Any]]:
    """The run's findings: the rejection log's list (a superset) else validation's, plus supersede notes."""
    seen, result = set(), []
    for raw in [*(fact["rejection"] or fact["validation"]), *fact["superseded"]]:
        finding = _finding(raw)
        key = (finding["code"], finding["message"])
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result


def _key_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def rank(f):
        return -1 if f["code"] == "SUPERSEDED_BY_REVISION" else SEVERITY_RANK.get(f["severity"], 3)
    by_code: dict[str, dict[str, Any]] = {}
    for f in sorted(findings, key=rank):
        by_code.setdefault(f["code"], {k: f[k] for k in ("code", "severity", "message")})
    return list(by_code.values())[:KEY_FINDINGS]


def _run(row: sqlite3.Row, fact: dict[str, Any], now: datetime) -> dict[str, Any]:
    stage_entered = fact["last_ts"] or row["uploaded_at"]
    return {
        "id": row["id"], "file_name": row["file_name"], "format": file_format(row["file_name"]),
        "invoice_number": row["invoice_number"], "vendor": row["vendor"], "amount_usd": _money(row["total_usd"]),
        "stage": row["stage"], "status": row["status"], "final_status": row["final_status"],
        "decided_by": row["decided_by"], "uploaded_at": row["uploaded_at"], "completed_at": row["completed_at"],
        "stage_entered_at": stage_entered, "time_in_stage_s": _seconds(stage_entered, now),
        "processing_s": _seconds(row["uploaded_at"], _parse(row["completed_at"])),
    }


def run_summary(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    """One run as list rows show it (used to enrich SSE events)."""
    row = conn.execute("SELECT * FROM invoice_runs WHERE id = ?", (run_id,)).fetchone()
    return None if row is None else _run(row, _run_facts(conn, [run_id])[run_id], now_utc())


# --- invoice views ---------------------------------------------------------------------------

def queue_view(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Unresolved runs: stage Uploaded, Extracting, Validating, Deciding, or Awaiting review (F23)."""
    rows = conn.execute(f"SELECT * FROM invoice_runs WHERE stage IN ({_marks(QUEUE_STAGES)}) "
                        "ORDER BY uploaded_at, id", QUEUE_STAGES).fetchall()
    facts, now = _run_facts(conn, [r["id"] for r in rows]), now_utc()
    result = []
    for row in rows:
        fact = facts[row["id"]]
        item = _run(row, fact, now)
        if row["status"] == "Awaiting review":
            label = "Awaiting review"
        elif row["stage"] == "Extracting" and fact["failed_attempts"]:
            label = "Retrying extraction"
        else:
            label = "Processing"  # Uploaded, Processing, or a claimed review that is Resuming
        item |= {"run_status": row["status"], "status": label}
        result.append(item)
    return result


def audit_view(conn: sqlite3.Connection, status: str | None = None, date_from: date | None = None,
               date_to: date | None = None, search: str | None = None) -> list[dict[str, Any]]:
    """Resolved runs with final status, decided by, and up to 3 key findings (F24). Filters combine."""
    rows = conn.execute("SELECT * FROM invoice_runs WHERE status = 'Resolved' "
                        "ORDER BY completed_at DESC, id DESC").fetchall()
    statuses = {s.strip().casefold() for s in status.split(",") if s.strip()} if status else set()
    tz = load_payment_timing(conn).tz
    rows = [r for r in rows
            if (not statuses or (r["final_status"] or "").casefold() in statuses)
            and _in_range(_local_date(r["completed_at"], tz), date_from, date_to)
            and (not search or any(_matches(r[c], search) for c in ("file_name", "invoice_number", "vendor")))]
    facts, now = _run_facts(conn, [r["id"] for r in rows]), now_utc()
    result = []
    for row in rows:
        findings = _findings(facts[row["id"]])
        result.append(_run(row, facts[row["id"]], now)
                      | {"key_findings": _key_findings(findings), "findings_count": len(findings)})
    return result


def review_view(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Runs paused for a person, with why each is held and the AI recommendation (F25)."""
    reviews = workflow.list_reviews()
    ids = [r["run_id"] for r in reviews]
    if not ids:
        return []
    rows = {r["id"]: r for r in conn.execute(f"SELECT * FROM invoice_runs WHERE id IN ({_marks(ids)})", ids)}
    held_at = {r["run_id"]: r["ts"] for r in conn.execute(
        f"SELECT run_id, MAX(ts) AS ts FROM audit_log WHERE event = 'review.enqueued' AND run_id IN ({_marks(ids)}) "
        "GROUP BY run_id", ids)}
    facts, now = _run_facts(conn, ids), now_utc()
    result = []
    for review in reviews:
        run_id = review["run_id"]
        hold = payments.review_hold(run_id, conn=conn)
        details = hold.details if hold else {}
        by_code = {f["code"]: f for f in _findings(facts[run_id])}
        findings = [{k: v for k, v in by_code.get(code, {"code": code}).items() if k != "evidence"}
                    for code in review["findings"]]
        payment_failed = review["kind"] == "payment_failure"
        result.append(_run(rows[run_id], facts[run_id], now) | {
            "hold_kind": review["kind"],
            "reason": "Payment failed" if payment_failed else review["reason"],
            "detail": review["reason"],
            "last_error": details.get("last_error"),
            "attempts": details.get("attempts"),
            "findings": findings,
            "ai_recommendation": review["ai_recommendation"],
            "ai_rationale": review["ai_rationale"],
            "overpaid_usd": _money(review["overpaid"]),
            "paid_amount_usd": _money(details.get("paid_amount")),
            "waiting_since": held_at.get(run_id),
            "waiting_s": _seconds(held_at.get(run_id), now),
        })
    return result


def run_exists(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM invoice_runs WHERE id = ?", (run_id,)).fetchone()


def invoice_detail(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    """Full record (F30): extracted fields, findings, drafts and critiques, reviews, payments, timeline."""
    row = run_exists(conn, run_id)
    if row is None:
        return None
    state = workflow.run_state(run_id)
    trace = read_trace(run_id, conn=conn)
    fact = _run_facts(conn, [run_id])[run_id]
    if state is not None and state.findings:
        findings = [_finding(f.model_dump(mode="json")) for f in state.findings]
        known = {(f["code"], f["message"]) for f in findings}
        findings += [f for f in map(_finding, fact["superseded"]) if (f["code"], f["message"]) not in known]
    else:
        findings = _findings(fact)

    def llm_entries(event: str, key: str) -> list[dict[str, Any]]:
        return [{"round": e["payload"].get("round"), key: e["payload"].get(key), "provider": e["payload"].get("provider"),
                 "model": e["payload"].get("model"), "ts": e["ts"]} for e in trace if e["event"] == event]

    rejection = next((e["payload"] for e in reversed(trace) if e["event"] == "rejection.recorded"), None)
    hold = payments.review_hold(run_id, conn=conn) if row["status"] in ("Awaiting review", "Resuming") else None
    queue_rows = [dict(r) for r in conn.execute("SELECT * FROM payment_queue WHERE run_id = ? ORDER BY id", (run_id,))]
    keys = {row_key(r) for r in queue_rows}
    ledger = [dict(r) for r in conn.execute(
        f"SELECT * FROM payments WHERE idempotency_key IN ({_marks(keys)}) ORDER BY id", list(keys))] if keys else []
    return _run(row, fact, now_utc()) | {
        "invoice": state.invoice.model_dump(mode="json") if state and state.invoice else None,
        "extracted": state.extracted if state else None,
        "findings": findings,
        "decision": state.decision.model_dump(mode="json") if state and state.decision else None,
        "drafts": llm_entries("approval.draft", "draft"),
        "critiques": llm_entries("approval.critique", "critique"),
        "reviews": [dict(r) for r in conn.execute(
            "SELECT reviewer, decision, rationale, decided_at FROM review_decisions WHERE run_id = ? ORDER BY id",
            (run_id,))],
        "hold": {"kind": hold.kind, "reason": hold.reason, "details": hold.details} if hold else None,
        "payment_queue": queue_rows,
        "payments": ledger,
        "rejection": rejection,
        "timeline": [{k: e[k] for k in ("ts", "agent", "event", "payload")} for e in trace],
    }


# --- payments ---------------------------------------------------------------------------------

def _currency_by_run(conn: sqlite3.Connection, run_ids: list[str]) -> dict[str, dict[str, str]]:
    result = {}
    for run_id, fact in _run_facts(conn, run_ids).items():
        for finding in _findings(fact):
            if finding["code"] == "CURRENCY_CONVERTED":
                evidence = finding["evidence"]
                result[run_id] = {"currency": evidence.get("currency"), "amount": _money(evidence.get("original_total"))}
    return result


def payments_view(conn: sqlite3.Connection, date_from: date | None = None, date_to: date | None = None,
                  vendor: str | None = None) -> dict[str, Any]:
    """Paid invoices (F26), oldest first, with the total paid for the filter."""
    paid_rows = {}
    for q in conn.execute("SELECT * FROM payment_queue WHERE status = 'paid' ORDER BY id"):
        paid_rows[row_key(q)] = q
    runs = {r["id"]: r for r in conn.execute("SELECT * FROM invoice_runs")}
    batches = {b["batch_id"]: b for b in conn.execute("SELECT * FROM payment_batches")}
    tz = load_payment_timing(conn).tz
    ledger = [p for p in conn.execute("SELECT * FROM payments ORDER BY paid_at, id")
              if _matches(p["vendor"], vendor) and _in_range(_local_date(p["paid_at"], tz), date_from, date_to)]
    queue_of = {p["id"]: paid_rows.get(p["idempotency_key"]) for p in ledger}
    currency = _currency_by_run(conn, sorted({q["run_id"] for q in queue_of.values() if q is not None}))
    rows = []
    for p in ledger:
        q = queue_of[p["id"]]
        run = runs.get(q["run_id"]) if q is not None else None
        batch = batches.get(p["batch_id"])
        fx = currency.get(q["run_id"]) if q is not None else None
        kind = q["kind"] if q is not None else None
        revision = q["revision"] if q is not None else None
        rows.append({
            "payment_id": p["payment_id"], "run_id": q["run_id"] if q is not None else None,
            "file_name": run["file_name"] if run else None,
            "invoice_number": q["invoice_number"] if q is not None else None, "revision": revision,
            "vendor": p["vendor"], "amount_usd": _money(p["amount_usd"]),
            "original_amount": fx["amount"] if fx else None, "original_currency": fx["currency"] if fx else None,
            "kind": kind, "delta_label": f"Delta for R{revision}" if kind == "delta" else None,
            "invoice_total_usd": _money(run["total_usd"]) if run else None,
            "approved_by": run["decided_by"] if run else None, "paid_at": p["paid_at"],
            "idempotency_key": p["idempotency_key"], "batch_id": p["batch_id"],
            "batch_trigger": batch["trigger"] if batch else None,
            "batch_trigger_label": TRIGGER_LABELS.get(batch["trigger"]) if batch else None,
            "released_by": batch["released_by"] if batch else None,
        })
    return {"rows": rows, "count": len(rows), "total_usd": _sum(r["amount_usd"] for r in rows),
            "server_time": server_time()}


def batches_view(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Batch history (newest first): trigger, released by, count, total, failures."""
    return [{
        "batch_id": b["batch_id"], "trigger": b["trigger"], "trigger_label": TRIGGER_LABELS.get(b["trigger"]),
        "released_by": b["released_by"], "started_at": b["started_at"], "finished_at": b["finished_at"],
        "running": b["finished_at"] is None, "count": b["count"], "total_usd": _money(b["total_usd"]),
        "failed_count": b["failed_count"],
    } for b in conn.execute("SELECT * FROM payment_batches ORDER BY started_at DESC, batch_id DESC")]


def _batch_label(when: datetime, now: datetime, tz_name: str) -> str:
    local_now = now.astimezone(ZoneInfo(tz_name))
    day = {0: "Today", 1: "Tomorrow"}.get((when.date() - local_now.date()).days, when.strftime("%a %b %d"))
    clock = when.strftime("%I:%M %p").lstrip("0")
    zone = "CT" if tz_name == "America/Chicago" else when.tzname()
    return f"{day} {clock} {zone}"


def payment_queue_view(conn: sqlite3.Connection, now: datetime | None = None) -> dict[str, Any]:
    """Rows queued, paying, or failed (F40), with count, total, and the payment mode from the admin settings:
    delay on or off, the next end-of-day batch (null when none is scheduled), and pay when queue empty."""
    settings, timing, now = get_settings(), load_payment_timing(conn), now or now_utc()
    rows = [{
        "id": r["id"], "run_id": r["run_id"], "file_name": r["file_name"], "invoice_number": r["invoice_number"],
        "revision": r["revision"], "vendor": r["vendor"], "amount_usd": _money(r["amount_usd"]), "kind": r["kind"],
        "approved_by": r["decided_by"], "queued_at": r["queued_at"], "status": r["status"],
        "attempts": r["attempts"], "last_error": r["last_error"], "batch_id": r["batch_id"],
    } for r in conn.execute(
        f"SELECT q.*, r.decided_by, r.file_name FROM payment_queue q LEFT JOIN invoice_runs r ON r.id = q.run_id "
        f"WHERE q.status IN ({_marks(OPEN_PAYMENT_STATUSES)}) ORDER BY q.id", OPEN_PAYMENT_STATUSES)]
    next_batch = payments.next_batch_time(now, timing)
    return {
        "rows": rows, "count": len(rows), "total_usd": _sum(r["amount_usd"] for r in rows),
        "delay_payments": timing.delay_payments, "pay_at_end_of_day": timing.pay_at_end_of_day,
        "next_batch_at": next_batch.isoformat() if next_batch else None,
        "next_batch_label": _batch_label(next_batch, now, timing.end_of_day_timezone) if next_batch else None,
        "timezone": timing.end_of_day_timezone, "pay_when_queue_empty": timing.pay_when_queue_empty,
        "idle_delay_s": settings.payment_idle_delay_s, "batch_running": payments.is_batch_running(),
        "server_time": server_time(),
    }


# --- stats ------------------------------------------------------------------------------------

def llm_info() -> dict[str, Any]:
    """Active provider and model (the AI VP's, which is LLM_PROVIDER unless overridden), every role,
    and the key status (`configured`, `missing_key`)."""
    roles = active_models()
    primary = roles.get("approval") or next(iter(roles.values()))
    status = key_status()
    return {"provider": primary["provider"], "model": primary["model"], "roles": roles,
            "configured": status.configured, "missing_key": status.missing_key}


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Badge and tile counts (F21, F31). "Today" is the local day in the admin end-of-day timezone."""
    tz = load_payment_timing(conn).tz
    today = _local_date(now_utc().isoformat(), tz)
    runs = conn.execute("SELECT stage, status, final_status, total_usd, completed_at FROM invoice_runs").fetchall()
    open_rows = conn.execute(f"SELECT amount_usd FROM payment_queue WHERE status IN "
                             f"({_marks(OPEN_PAYMENT_STATUSES)})", OPEN_PAYMENT_STATUSES).fetchall()
    ledger = conn.execute("SELECT amount_usd, paid_at FROM payments").fetchall()
    rejected = [r for r in runs if r["final_status"] in REJECTED_STATUSES]
    return {
        "in_queue": sum(r["stage"] in QUEUE_STAGES for r in runs),
        "processing": sum(r["stage"] in PROCESSING_STAGES for r in runs),
        "awaiting_review": sum(r["status"] == "Awaiting review" for r in runs),
        "payment_queue": len(open_rows),
        "paid_today": sum(_local_date(p["paid_at"], tz) == today for p in ledger),
        "rejected_today": sum(_local_date(r["completed_at"], tz) == today for r in rejected),
        "dollars_queued": _sum(r["amount_usd"] for r in open_rows),
        "dollars_paid": _sum(p["amount_usd"] for p in ledger),
        "dollars_blocked": _sum(r["total_usd"] for r in rejected),
        "duplicates_caught": sum(r["final_status"] == "Duplicate" for r in runs),
        "llm": llm_info(),
        "server_time": server_time(),
    }
