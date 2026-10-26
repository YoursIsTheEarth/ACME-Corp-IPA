"""Command-line entry point (`python main.py ...`, F18, F19).

    python main.py --invoice_path=data/invoices/invoice_1001.txt [--provider grok|claude] [--json] [--pay]
    python main.py --batch data/invoices [--provider grok|claude] [--pay] [--released-by NAME] [--json]
    python main.py --explain <run_id>
    python main.py payments run [--released-by NAME] [--json]
    python main.py review [<run_id> --decision approve|reject --reviewer NAME --rationale TEXT] [--json]

Results go to stdout (rich, or JSON lines with --json); JSON logs go to stderr (WARNING and up,
everything with --verbose or --json).
"""

import argparse
import contextlib
import json
import logging
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from acme.db import connect, init_schema
from acme.db.seed import seed
from acme.llm import ProviderConfigError, key_status, missing_key_message, use_provider
from acme.logging import configure_logging, dumps, read_trace

log = logging.getLogger(__name__)

OUTCOME_STYLE = {"APPROVE": "bold green", "REJECT": "bold red", "NEEDS_REVIEW": "bold yellow"}
SEVERITY_STYLE = {"CRITICAL": "red", "WARNING": "yellow", "INFO": "cyan"}
REPORT_PATH = Path("reports") / "summary.md"


def _common(parser: argparse.ArgumentParser, suppress: bool) -> None:
    default = argparse.SUPPRESS if suppress else None
    parser.add_argument("--provider", default=default, choices=["grok", "claude"],
                        help="LLM provider for this command: grok or claude (needs XAI_API_KEY or ANTHROPIC_API_KEY)")
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS if suppress else False,
                        help="print one JSON object per run instead of formatted output")
    parser.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS if suppress else False,
                        help="also print INFO-level JSON logs on stderr")
    parser.add_argument("--released-by", dest="released_by", default=argparse.SUPPRESS if suppress else "cli",
                        help="name recorded on payment batches (1-50 characters, default: cli)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="main.py", description="Acme Invoice Agents")
    parser.add_argument("--invoice_path", help="invoice file to process")
    parser.add_argument("--batch", metavar="DIR", help="process every supported file in DIR, in filename order")
    parser.add_argument("--pay", action="store_true", help="run one payment batch after processing")
    parser.add_argument("--explain", metavar="RUN_ID", help="replay a run's audit trail")
    _common(parser, suppress=False)
    commands = parser.add_subparsers(dest="command")

    pay = commands.add_parser("payments", help="payment batches")
    pay.add_argument("action", choices=["run"], help="run one payment batch now")
    _common(pay, suppress=True)

    review = commands.add_parser("review", help="list held invoices, or decide one")
    review.add_argument("run_id", nargs="?", help="run to decide (omit to list held invoices)")
    review.add_argument("--decision", choices=["approve", "reject"])
    review.add_argument("--reviewer", help="your name (1-50 characters)")
    review.add_argument("--rationale", help="why (at least 15 characters)")
    _common(review, suppress=True)
    return parser


class Output:
    """Rich on stdout, or JSON lines on stdout with --json."""

    def __init__(self, as_json: bool) -> None:
        self.json = as_json
        self.console = Console(highlight=False, soft_wrap=True)

    def emit(self, obj: dict[str, Any]) -> None:
        print(dumps(obj), flush=True)

    def text(self, value: str, style: str | None = None) -> None:
        if not self.json:
            self.console.print(Text(value, style=style or ""))

    def error(self, message: str) -> None:
        print(f"error: {message}", file=sys.stderr)


# --- Processing ------------------------------------------------------------------------------

def _ensure_db(out: Output) -> None:
    """Create missing tables; seed the reference data when the inventory is empty (fresh checkout)."""
    conn = connect()
    try:
        init_schema(conn)
        if conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0:
            seed(conn)
            log.info("database_seeded", extra={"data": {"reason": "inventory was empty"}})
            out.text("Seeded an empty acme.db with the reference inventory and vendors.", "dim")
    finally:
        conn.close()


def _recover(out: Output, provider: str | None) -> None:
    """Startup recovery: interrupted payment batch, then runs left mid-pipeline (processed again once
    an LLM key is set; until then they wait as Uploaded)."""
    from acme.payments import recover_interrupted_batch
    from acme.workflow import process_run, recover_orphaned_runs

    recovered = recover_interrupted_batch()
    if recovered["paid"] or recovered["requeued"]:
        out.text(f"Recovered an interrupted payment batch: {recovered['paid']} paid, "
                 f"{recovered['requeued']} re-queued.", "yellow")
    orphaned = recover_orphaned_runs()
    if orphaned and not key_status().configured:
        out.text(f"{len(orphaned)} interrupted run(s) wait for an LLM key before they are processed.", "yellow")
        return
    for run_id in orphaned:
        out.text(f"Resuming interrupted run {run_id}", "yellow")
        _report(out, process_run(run_id, provider))


def _stage_printer(out: Output) -> Callable[[str, dict], None] | None:
    if out.json:
        return None

    def on_event(name: str, data: dict) -> None:
        if name == "invoice.stage_changed" and data.get("status") == "Processing":
            out.text(f"  > {data['stage']}", "dim")
    return on_event


def _report(out: Output, result) -> None:
    if out.json:
        out.emit(result.to_json())
        return
    console = out.console
    if result.findings:
        table = Table(title="Findings", title_justify="left")
        for column in ("Severity", "Code", "Message"):
            table.add_column(column)
        for f in result.findings:
            table.add_row(Text(f.severity.value, style=SEVERITY_STYLE[f.severity.value]), f.code.value,
                          Text(f.message))
        console.print(table)
    else:
        out.text("No findings.", "green")
    outcome = result.outcome or "NONE"
    status = result.final_status or result.status
    line = Text("Outcome: ")
    line.append(outcome, style=OUTCOME_STYLE.get(outcome, "bold"))
    line.append(f"  ({status})")
    console.print(line)
    amount = f"${result.total_usd:,.2f}" if result.total_usd is not None else "-"
    out.text(f"Invoice: {result.invoice_number or '-'}  Vendor: {result.vendor or '-'}  Amount (USD): {amount}")
    out.text(f"Decided by: {result.decided_by or '-'}")
    if result.rationale:
        out.text(f"Rationale: {result.rationale}")
    out.text(f"Run ID: {result.run_id}", "bold")


def _results_table(out: Output, results) -> None:
    table = Table(title="Results", title_justify="left")
    for column in ("File", "Invoice #", "Vendor", "Amount (USD)", "Outcome", "Status", "Key findings"):
        table.add_column(column, overflow="fold", justify="right" if column == "Amount (USD)" else "left")
    for r in results:
        codes = sorted({f.code.value for f in r.findings if f.severity.value != "INFO"} or
                       {f.code.value for f in r.findings})
        table.add_row(r.file, r.invoice_number or "-", Text(r.vendor or "-"),
                      f"{r.total_usd:,.2f}" if r.total_usd is not None else "-",
                      Text(r.outcome or "-", style=OUTCOME_STYLE.get(r.outcome or "", "")),
                      r.final_status or r.status or "-", ", ".join(codes))
    out.console.print(table)


def _pay(out: Output, released_by: str) -> int:
    from acme.payments import BatchAlreadyRunning, InvalidBatchRequest, payable_count, run_batch
    from acme.settings import get_settings

    conn = connect()
    try:
        payable = payable_count(conn, get_settings().payment_max_attempts)
    finally:
        conn.close()
    if payable == 0:
        if out.json:
            out.emit({"batch": None, "message": "nothing is queued for payment"})
        out.text("Nothing is queued for payment; no payments made.")
        return 0
    try:
        # mock_payment prints to stdout; keep stdout pure JSON in --json mode.
        with contextlib.redirect_stdout(sys.stderr) if out.json else contextlib.nullcontext():
            batch = run_batch("pay_all", released_by)
    except (BatchAlreadyRunning, InvalidBatchRequest) as exc:
        out.error(str(exc))
        return 1
    if out.json:
        out.emit({"batch": {"batch_id": batch.batch_id, "trigger": batch.trigger, "released_by": batch.released_by,
                            "paid": batch.count, "total_usd": str(batch.total_usd), "failed": batch.failed_count}})
    else:
        out.text(f"Payment batch {batch.batch_id}: {batch.count} paid, total ${batch.total_usd:,.2f}, "
                 f"{batch.failed_count} failed (released by {batch.released_by})", "bold")
    return 0


def _process(args, out: Output) -> int:
    from acme.summary import render_markdown, summarize_runs
    from acme.workflow import folder_files, run_invoice

    if args.invoice_path:
        path = Path(args.invoice_path)
        if not path.is_file():
            out.error(f"invoice file not found: {path}")
            return 1
        paths = [path]
    else:
        folder = Path(args.batch)
        if not folder.is_dir():
            out.error(f"invoice folder not found: {folder}")
            return 1
        paths = folder_files(folder)

    results = []
    for i, path in enumerate(paths, 1):
        out.text(f"[{i}/{len(paths)}] {path.name}" if args.batch else f"Processing {path}", "bold")
        result = run_invoice(path, args.provider, _stage_printer(out))
        results.append(result)
        if args.batch and not out.json:
            out.text(f"  -> {result.outcome} ({result.final_status or result.status})  run {result.run_id}")
        else:
            _report(out, result)

    if args.batch and not out.json:
        _results_table(out, results)
    code = _pay(out, args.released_by) if args.pay else 0
    if args.batch:
        summary = summarize_runs([r.run_id for r in results])
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(render_markdown(summary), encoding="utf-8")
        if out.json:
            out.emit({"summary": {k: str(v) for k, v in summary.__dict__.items()}})
        else:
            out.console.print(render_markdown(summary), markup=False)
            out.text(f"Summary written to {REPORT_PATH}")
    return code


# --- Review ----------------------------------------------------------------------------------

def _review(args, out: Output) -> int:
    from acme.workflow import ReviewConflict, ReviewInputError, list_reviews, resume_review

    if args.run_id is None:
        reviews = list_reviews()
        if out.json:
            for item in reviews:
                out.emit(item)
            return 0
        if not reviews:
            out.text("No invoices are awaiting review.")
            return 0
        out.text(f"{len(reviews)} invoice(s) awaiting review", "bold")
        for r in reviews:
            amount = f"${Decimal(r['total_usd']):,.2f}" if r["total_usd"] else "-"
            out.text(f"{r['run_id']}  {r['invoice_number'] or '-'}  {r['vendor'] or '-'}  {amount}", "bold")
            out.text(f"  Why held ({r['kind']}): {r['reason']}")
            out.text(f"  AI recommendation: {r['ai_recommendation']} - {r['ai_rationale']}")
        return 0

    missing = [flag for flag in ("decision", "reviewer", "rationale") if getattr(args, flag) is None]
    if missing:
        out.error(f"deciding a run needs {', '.join('--' + m for m in missing)}")
        return 1
    try:
        result = resume_review(args.run_id, args.decision, args.reviewer, args.rationale)
    except ReviewInputError as exc:
        out.error(f"{exc}; the run is still awaiting review")
        return 1
    except ReviewConflict as exc:
        out.error(str(exc))
        return 1
    _report(out, result)
    return 0


# --- Explain ---------------------------------------------------------------------------------

def _finding_line(f: dict) -> str:
    evidence = json.dumps(f.get("evidence") or {}, ensure_ascii=False)
    return f"    {f.get('severity')} {f.get('code')}: {f.get('message')}  evidence={evidence}"


def _llm(p: dict) -> str:
    return f" [{p['provider']}/{p['model']}]" if "provider" in p else ""


def _explain_lines(event: str, p: dict) -> list[str]:
    if event == "extraction_attempt":
        return [f"  attempt {p.get('attempt')} ({p.get('format')}): {p.get('outcome')}"]
    if event == "ingestion.result":
        lines = [f"  format {p.get('format')}, {p.get('attempts')} attempt(s), {p.get('retries')} retries"]
        return lines + [f"  retry error: {e}" for e in p.get("errors") or []]
    if event == "normalized":
        number = p.get("invoice_number") or {}
        lines = [f"  invoice number {number.get('raw')!r} -> {number.get('normalized')}"]
        lines += [f"  item {m['raw_name']!r} -> {m['sku']} ({m['method']})" for m in p.get("sku_matches") or []]
        return lines + [f"  OCR repair {r['field']}: {r['before']!r} -> {r['after']!r}" for r in p.get("ocr_repairs") or []]
    if event == "validation.tool_calls":
        return [f"  round {p.get('round')}{_llm(p)}: {', '.join(p.get('tools') or [])}"]
    if event in ("validation.findings", "validation.fallback"):
        lines = [f"  error: {p['error']}"] if p.get("error") else []
        lines += [f"  checks run without the LLM: {', '.join(p['swept'])}"] if p.get("swept") else []
        return lines + ([_finding_line(f) for f in p.get("findings") or []] or ["  no findings"])
    if event == "approval.policy":
        return [f"  floor {p.get('floor')}; rules fired: {', '.join(p.get('rules') or [])}"]
    if event == "approval.draft":
        d = p.get("draft") or {}
        return [f"  AI VP draft round {p.get('round')}{_llm(p)}: {d.get('outcome')} - {d.get('rationale')}"]
    if event == "approval.critique":
        c = p.get("critique") or {}
        verdict = "passes" if c.get("passes") else f"fails: {'; '.join(c.get('issues') or [])}"
        return [f"  Critic round {p.get('round')}{_llm(p)}: {verdict}"]
    if event == "approval.clamped":
        return [f"  LLM override blocked: {p.get('source')} proposed {p.get('proposed')}, final {p.get('final')}"]
    if event == "approval.decision":
        d = p.get("decision") or {}
        return [f"  decision {d.get('outcome')} by {d.get('decided_by')}: {d.get('rationale')}"]
    if event == "review.enqueued":
        return [f"  held for review ({p.get('kind')}): {p.get('reason')}"]
    if event == "review.decision":
        return [f"  reviewer {p.get('reviewer')} decided {p.get('decision')}: {p.get('rationale')}"]
    if event == "rejection.recorded":
        lines = [f"  {p.get('final_status')} by {p.get('decided_by')}: {p.get('rationale')}",
                 f"  rules: {', '.join(p.get('rules_applied') or [])}"]
        return lines + [_finding_line(f) for f in p.get("findings") or []]
    if event in ("payment.queued", "payment.created"):
        return [f"  {p.get('kind')} {p.get('amount_usd')} USD to {p.get('vendor')} (row {p.get('row_id')})"
                + (f", payment {p['payment_id']}" if p.get("payment_id") else "")]
    if event == "disposition.outcome":
        return [f"  outcome {p.get('outcome')} -> {p.get('final_status') or p.get('status')}"]
    return [f"  {json.dumps(p, ensure_ascii=False)[:300]}"]


def _explain(run_id: str, out: Output) -> int:
    entries = read_trace(run_id)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM invoice_runs WHERE id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None and not entries:
        out.error(f"run not found: {run_id}")
        return 1
    if out.json:
        for entry in entries:
            out.emit(entry)
        return 0
    if row is not None:
        out.text(f"Run {run_id}: {row['file_name']}  {row['invoice_number'] or ''} {row['vendor'] or ''}  "
                 f"status {row['final_status'] or row['status']}", "bold")
    for entry in entries:
        out.text(f"{entry['ts']}  {entry['agent']}  {entry['event']}", "cyan")
        for line in _explain_lines(entry["event"], entry["payload"]):
            out.text(line)
    return 0


# --- Main ------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(logging.INFO if args.verbose or args.json else logging.WARNING)
    out = Output(args.json)
    processing = bool(args.invoice_path or args.batch)
    if args.invoice_path and args.batch:
        out.error("use either --invoice_path or --batch, not both")
        return 2
    try:
        with use_provider(args.provider):
            status = key_status()
    except ProviderConfigError as exc:
        out.error(str(exc))
        return 2
    if processing and not status.configured:
        message = missing_key_message(status.missing_key, status.provider)
        if out.json:
            out.emit({"error": message, "missing_key": status.missing_key})
        else:
            out.error(message)
        return 2
    if not (processing or args.explain or args.command or args.pay):
        parser.print_help()
        return 0

    _ensure_db(out)
    if args.explain:
        return _explain(args.explain, out)
    with use_provider(args.provider):
        _recover(out, args.provider)
    if args.command == "review":
        return _review(args, out)
    if args.command == "payments" or (args.pay and not processing):
        return _pay(out, args.released_by)
    return _process(args, out)
