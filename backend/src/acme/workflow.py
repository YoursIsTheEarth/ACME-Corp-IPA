"""Runner API over the compiled graph. The CLI and the API call only these.

    result = run_invoice("data/invoices/invoice_1001.txt")          # create_run + process_run
    results = run_folder("data/invoices")                            # sorted filename order
    run_id = create_run(path); process_run(run_id, on_event=cb)      # API: row first, worker later
    resume_review(run_id, "approve", "Dana", "Rush pricing agreed by procurement")
    recover_orphaned_runs()                                          # startup: mid-pipeline -> Uploaded

`invoice_runs` vocabulary written here and by the disposition tools:
status Uploaded -> Processing (stage Extracting / Validating / Deciding) -> Queued for payment |
Awaiting review | Resolved (final_status Paid, Revised, Rejected, Duplicate, Superseded, Credit confirmed);
a claimed review is status Resuming until its disposition finishes.
"""

import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from langgraph.types import Command

from acme import payments
from acme.db import connect
from acme.graph import WorkflowState, compiled_graph
from acme.graph.nodes import EventCallback, on_event_var
from acme.llm import use_provider
from acme.logging import audit, run_context
from acme.models import Decision, Finding, Outcome
from acme.payments._store import immediate, utcnow
from acme.settings import get_settings

log = logging.getLogger(__name__)

PROCESSING_STAGES = ("Uploaded", "Extracting", "Validating", "Deciding")
DECISIONS = ("approve", "reject")
MIN_RATIONALE = 15
MAX_REVIEWER = 50


class ReviewConflict(RuntimeError):
    """The run is not awaiting review (already decided, still processing, or unknown)."""

    def __init__(self, run_id: str, status: str | None) -> None:
        super().__init__(f"run {run_id} is no longer awaiting review (status: {status or 'not found'})")
        self.run_id, self.status = run_id, status


class ReviewInputError(ValueError):
    """Bad decision, reviewer name (1-50 characters after trimming), or rationale (at least 15 characters)."""


@dataclass
class RunResult:
    run_id: str
    file: str
    status: str | None
    stage: str | None
    final_status: str | None
    outcome: str | None
    invoice_number: str | None
    vendor: str | None
    total_usd: Decimal | None
    decided_by: str | None
    rationale: str | None
    findings: list[Finding] = field(default_factory=list)

    @property
    def held(self) -> bool:
        return self.status == "Awaiting review"

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "file": self.file, "invoice_number": self.invoice_number,
            "vendor": self.vendor, "total_usd": None if self.total_usd is None else str(self.total_usd),
            "outcome": self.outcome, "status": self.status, "final_status": self.final_status,
            "findings": [{"code": f.code.value, "severity": f.severity.value, "message": f.message}
                         for f in self.findings],
            "decided_by": self.decided_by, "rationale": self.rationale,
        }


def _config(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}}


def _run_row(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM invoice_runs WHERE id = ?", (run_id,)).fetchone()


def _result(run_id: str, state: WorkflowState | None) -> RunResult:
    conn = connect()
    try:
        row = _run_row(conn, run_id)
    finally:
        conn.close()
    decision = state.decision if state else None
    invoice = state.invoice if state else None
    return RunResult(
        run_id=run_id, file=row["file_name"], status=row["status"], stage=row["stage"],
        final_status=row["final_status"], outcome=decision.outcome.value if decision else None,
        invoice_number=row["invoice_number"] or (invoice.invoice_number if invoice else None),
        vendor=row["vendor"] or (invoice.vendor_name if invoice else None),
        total_usd=Decimal(row["total_usd"]) if row["total_usd"] else None,
        decided_by=row["decided_by"] or (decision.decided_by if decision else None),
        rationale=decision.rationale if decision else None,
        findings=list(state.findings) if state else [],
    )


def _state(values: dict[str, Any] | None) -> WorkflowState | None:
    if not values:
        return None
    return WorkflowState.model_validate({k: v for k, v in values.items() if not k.startswith("__")})


def run_state(run_id: str) -> WorkflowState | None:
    """The run's latest checkpointed state (findings, drafts, decision), or None."""
    with compiled_graph() as graph:
        return _state(graph.get_state(_config(run_id)).values)


# --- Processing ------------------------------------------------------------------------------

def create_run(path: str | Path, stored_path: str | Path | None = None,
               conn: sqlite3.Connection | None = None) -> str:
    """Insert an `invoice_runs` row (status/stage Uploaded) and return its run_id."""
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    own = conn is None
    conn = conn or connect()
    try:
        conn.execute("INSERT INTO invoice_runs (id, file_name, stored_path, uploaded_at, status, stage) "
                     "VALUES (?, ?, ?, ?, 'Uploaded', 'Uploaded')",
                     (run_id, Path(path).name, str(stored_path or path), utcnow()))
        conn.commit()
    finally:
        if own:
            conn.close()
    return run_id


def _fail_closed(run_id: str, exc: BaseException) -> None:
    """An unexpected error still ends the run with a disposition (REJECT), never mid-pipeline."""
    log.exception("workflow_failed", extra={"data": {"run_id": run_id}})
    rationale = f"Workflow error, rejected fail-closed: {type(exc).__name__}: {exc}"
    try:
        payments.record_rejection(run_id, Decision(outcome=Outcome.REJECT, rationale=rationale,
                                                   decided_by="Auto (rules)"), [])
        audit(run_id, "workflow", "workflow.failed", {"error": rationale})
    except Exception:
        log.exception("workflow_fail_closed_failed", extra={"data": {"run_id": run_id}})


def process_run(run_id: str, provider: str | None = None, on_event: EventCallback | None = None) -> RunResult:
    """Run an existing run (from `create_run`) through the graph to a disposition or a review hold.

    A run with an unfinished checkpoint continues from it; a run paused for review is left as is.
    """
    conn = connect()
    try:
        row = _run_row(conn, run_id)
    finally:
        conn.close()
    if row is None:
        raise KeyError(f"run {run_id} not found")
    token = on_event_var.set(on_event)
    state = None
    try:
        with use_provider(provider), run_context(run_id), compiled_graph() as graph:
            snapshot = graph.get_state(_config(run_id))
            if snapshot.interrupts:
                return _result(run_id, _state(snapshot.values))
            start = None if snapshot.next else WorkflowState(run_id=run_id, file_path=row["stored_path"])
            try:
                state = _state(graph.invoke(start, _config(run_id)))
            except Exception as exc:
                _fail_closed(run_id, exc)
                state = _state(graph.get_state(_config(run_id)).values)
    finally:
        on_event_var.reset(token)
    return _result(run_id, state)


def run_invoice(path: str | Path, provider: str | None = None, on_event: EventCallback | None = None) -> RunResult:
    """Process one file in a new run. Raises FileNotFoundError before creating a run if it is missing."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"invoice file not found: {path}")
    return process_run(create_run(path), provider, on_event)


def folder_files(directory: str | Path) -> list[Path]:
    """Supported invoice files in `directory`, in sorted filename order."""
    allowed = set(get_settings().allowed_upload_extensions)
    return sorted((p for p in Path(directory).iterdir() if p.is_file() and p.suffix.lower() in allowed),
                  key=lambda p: p.name)


def run_folder(directory: str | Path, provider: str | None = None,
               on_event: EventCallback | None = None) -> list[RunResult]:
    """One run per supported file, sequentially, in sorted filename order."""
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"invoice folder not found: {directory}")
    return [run_invoice(path, provider, on_event) for path in folder_files(directory)]


def recover_orphaned_runs(conn: sqlite3.Connection | None = None) -> list[str]:
    """Startup: runs left mid-pipeline (Uploaded/Extracting/Validating/Deciding) go back to Uploaded.

    Returns their ids, oldest first, for the caller to process again (`process_run` continues from
    the last checkpoint where there is one). Awaiting-review and Resuming runs are not touched.
    """
    own = conn is None
    conn = conn or connect()
    try:
        marks = ",".join("?" * len(PROCESSING_STAGES))
        with immediate(conn):
            ids = [r["id"] for r in conn.execute(
                f"SELECT id FROM invoice_runs WHERE stage IN ({marks}) AND status NOT IN "
                "('Awaiting review', 'Resuming') ORDER BY uploaded_at, id", PROCESSING_STAGES)]
            conn.executemany("UPDATE invoice_runs SET stage = 'Uploaded', status = 'Uploaded' WHERE id = ?",
                             [(i,) for i in ids])
        for run_id in ids:
            audit(run_id, "workflow", "run.recovered", {"reset_to": "Uploaded"}, conn=conn)
    finally:
        if own:
            conn.close()
    return ids


# --- Human review ----------------------------------------------------------------------------

def validate_review(decision: str, reviewer: str | None, rationale: str | None) -> tuple[str, str, str]:
    decision = (decision or "").strip().lower()
    if decision not in DECISIONS:
        raise ReviewInputError("decision must be approve or reject")
    reviewer = (reviewer or "").strip()
    if not 1 <= len(reviewer) <= MAX_REVIEWER:
        raise ReviewInputError(f"reviewer name must be 1 to {MAX_REVIEWER} characters")
    rationale = (rationale or "").strip()
    if len(rationale) < MIN_RATIONALE:
        raise ReviewInputError(f"rationale must be at least {MIN_RATIONALE} characters")
    return decision, reviewer, rationale


def record_review(run_id: str, decision: str, reviewer: str, rationale: str,
                  conn: sqlite3.Connection | None = None) -> None:
    """Validate, claim the run (`Awaiting review -> Resuming`), and store the decision. Does not resume.

    Raises ReviewInputError, or ReviewConflict when the run is not awaiting review.
    """
    decision, reviewer, rationale = validate_review(decision, reviewer, rationale)
    own = conn is None
    conn = conn or connect()
    try:
        with immediate(conn):
            claimed = conn.execute("UPDATE invoice_runs SET status = 'Resuming' WHERE id = ? "
                                   "AND status = 'Awaiting review'", (run_id,)).rowcount
            if not claimed:
                row = _run_row(conn, run_id)
                raise ReviewConflict(run_id, row["status"] if row else None)
            conn.execute("INSERT INTO review_decisions (run_id, reviewer, decision, rationale, decided_at) "
                         "VALUES (?, ?, ?, ?, ?)", (run_id, reviewer, decision, rationale, utcnow()))
        audit(run_id, "reviewer", "review.decision",
              {"decision": decision, "reviewer": reviewer, "rationale": rationale}, conn=conn)
    finally:
        if own:
            conn.close()


def continue_review(run_id: str, on_event: EventCallback | None = None) -> RunResult:
    """Resume a claimed (Resuming) run with its latest stored `review_decisions` row.

    Payment-failure holds (whose graph already ended) go to `resume_payment_failure`; every other
    hold resumes the paused graph, which continues to Disposition with the reviewer as the decider.
    """
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM review_decisions WHERE run_id = ? ORDER BY id DESC LIMIT 1",
                           (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ReviewConflict(run_id, "no review decision recorded")
    hold = payments.review_hold(run_id)
    if hold is not None and hold.kind == "payment_failure":
        payments.resume_payment_failure(run_id, row["decision"] == "approve", row["reviewer"], row["rationale"])
        return _result(run_id, run_state(run_id))
    token = on_event_var.set(on_event)
    try:
        with run_context(run_id), compiled_graph() as graph:
            if not graph.get_state(_config(run_id)).interrupts:
                raise ReviewConflict(run_id, "no paused workflow for this run")
            answer = {"decision": row["decision"], "reviewer": row["reviewer"], "rationale": row["rationale"]}
            state = _state(graph.invoke(Command(resume=answer), _config(run_id)))
    finally:
        on_event_var.reset(token)
    return _result(run_id, state)


def resume_review(run_id: str, decision: str, reviewer: str, rationale: str,
                  on_event: EventCallback | None = None) -> RunResult:
    """Decide a held run: `record_review` (validation + claim + `review_decisions`), then `continue_review`."""
    record_review(run_id, decision, reviewer, rationale)
    return continue_review(run_id, on_event)


def list_reviews() -> list[dict[str, Any]]:
    """Runs awaiting review with why each is held and the AI recommendation, oldest first."""
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM invoice_runs WHERE status = 'Awaiting review' "
                            "ORDER BY uploaded_at, id").fetchall()
    finally:
        conn.close()
    reviews = []
    for row in rows:
        hold = payments.review_hold(row["id"])
        details = hold.details if hold else {}
        reviews.append({
            "run_id": row["id"], "file": row["file_name"], "invoice_number": row["invoice_number"],
            "vendor": row["vendor"], "total_usd": row["total_usd"],
            "kind": hold.kind if hold else None, "reason": hold.reason if hold else None,
            "findings": details.get("findings", []), "ai_recommendation": details.get("ai_recommendation"),
            "ai_rationale": details.get("ai_rationale"), "overpaid": details.get("overpaid"),
        })
    return reviews


__all__ = [
    "ReviewConflict", "ReviewInputError", "RunResult", "continue_review", "create_run", "folder_files",
    "list_reviews", "process_run", "record_review", "recover_orphaned_runs", "resume_review", "run_folder",
    "run_invoice", "run_state", "validate_review",
]
