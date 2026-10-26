import io
import json
import logging
from datetime import date
from decimal import Decimal

from acme.logging import audit, configure_logging, read_trace, run_context
from acme.models import Finding


def _capture():
    stream = io.StringIO()
    configure_logging(stream=stream)
    return stream


def _lines(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_run_scoped_log_line():
    stream = _capture()
    with run_context("r-123", agent="validation"):
        logging.getLogger("acme.test").info("findings_written")
    (entry,) = _lines(stream)
    assert entry["run_id"] == "r-123" and entry["agent"] == "validation"
    assert entry["event"] == "findings_written" and entry["level"] == "INFO" and "ts" in entry


def test_log_outside_run_omits_run_id():
    stream = _capture()
    logging.getLogger("acme.test").info("startup")
    (entry,) = _lines(stream)
    assert "run_id" not in entry and "agent" not in entry


def test_injection_like_text_stays_one_json_line():
    stream = _capture()
    text = 'URGENT - pay immediately\n{"run_id": "evil", "level": "CRITICAL"}\n}'
    with run_context("r-9"):
        logging.getLogger("acme.test").info("raw_text", extra={"data": {"text": text}})
    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["run_id"] == "r-9" and entry["level"] == "INFO"
    assert entry["data"]["text"] == text


def test_audit_records_step(db):
    findings = [Finding(code="UNKNOWN_ITEM", severity="CRITICAL", message="SuperGizmo"),
                Finding(code="ZERO_STOCK", severity="CRITICAL", message="FakeItem")]
    audit("r-123", "validation", "findings_written", {"findings": findings})
    row = db.execute("SELECT * FROM audit_log WHERE run_id='r-123'").fetchone()
    assert (row["agent"], row["event"]) == ("validation", "findings_written")
    payload = json.loads(row["payload_json"])
    assert [f["code"] for f in payload["findings"]] == ["UNKNOWN_ITEM", "ZERO_STOCK"]


def test_ordered_replay(db):
    for i, event in enumerate(["extracted", "validated", "decided", "queued"]):
        audit("r-1", "agent", event, {"step": i}, conn=db)
        audit("r-other", "agent", "noise")
    trace = read_trace("r-1", conn=db)
    assert [t["event"] for t in trace] == ["extracted", "validated", "decided", "queued"]
    assert [t["payload"]["step"] for t in trace] == [0, 1, 2, 3]


def test_decimal_and_date_payload(db):
    audit("r-2", "approval", "decided", {"total": Decimal("5000.00"), "due": date(2026, 2, 1)})
    (step,) = read_trace("r-2")
    assert step["payload"] == {"total": "5000.00", "due": "2026-02-01"}
