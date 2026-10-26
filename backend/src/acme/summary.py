"""Batch summary (F31): outcome counts and dollars queued, paid, and blocked for a set of runs.

    summary = summarize_runs(run_ids)
    Path("reports/summary.md").write_text(render_markdown(summary))
"""

from dataclasses import dataclass
from decimal import Decimal

from acme.db import connect
from acme.payments.revisions import money

ZERO = Decimal("0")


@dataclass(frozen=True)
class Summary:
    runs: int
    paid: int
    queued: int
    superseded: int
    revised: int
    credit_confirmed: int
    held: int
    rejected: int  # Rejected + Duplicate
    duplicates: int
    usd_queued: Decimal
    usd_paid: Decimal
    usd_blocked: Decimal  # totals of rejected or held runs


def summarize_runs(run_ids: list[str]) -> Summary:
    conn = connect()
    try:
        marks = ",".join("?" * len(run_ids)) or "NULL"
        runs = conn.execute(f"SELECT id, status, final_status, total_usd FROM invoice_runs WHERE id IN ({marks})",
                            run_ids).fetchall()
        rows = conn.execute(f"SELECT status, amount_usd FROM payment_queue WHERE run_id IN ({marks})",
                            run_ids).fetchall()
    finally:
        conn.close()
    final = [r["final_status"] for r in runs]
    blocked = [r for r in runs if r["status"] == "Awaiting review" or r["final_status"] in ("Rejected", "Duplicate")]

    def total(values) -> Decimal:
        return money(sum((Decimal(v) for v in values if v), ZERO))

    return Summary(
        runs=len(runs),
        paid=final.count("Paid"),
        queued=sum(r["status"] == "Queued for payment" for r in runs),
        superseded=final.count("Superseded"),
        revised=final.count("Revised"),
        credit_confirmed=final.count("Credit confirmed"),
        held=sum(r["status"] == "Awaiting review" for r in runs),
        rejected=final.count("Rejected") + final.count("Duplicate"),
        duplicates=final.count("Duplicate"),
        usd_queued=total(r["amount_usd"] for r in rows if r["status"] in ("queued", "failed", "paying")),
        usd_paid=total(r["amount_usd"] for r in rows if r["status"] == "paid"),
        usd_blocked=total(r["total_usd"] for r in blocked),
    )


def render_markdown(summary: Summary) -> str:
    counts = [
        ("Invoices processed", summary.runs), ("Paid", summary.paid), ("Queued for payment", summary.queued),
        ("Superseded", summary.superseded), ("Revised (no payment due)", summary.revised),
        ("Credit confirmed", summary.credit_confirmed), ("Held for review", summary.held),
        ("Rejected", summary.rejected), ("Duplicates caught", summary.duplicates),
    ]
    dollars = [("Queued", summary.usd_queued), ("Paid", summary.usd_paid),
               ("Blocked (rejected or held)", summary.usd_blocked)]
    lines = ["# Invoice batch summary", "", "| Outcome | Count |", "| --- | ---: |"]
    lines += [f"| {label} | {count} |" for label, count in counts]
    lines += ["", "| Dollars (USD) | Amount |", "| --- | ---: |"]
    lines += [f"| {label} | ${amount:,.2f} |" for label, amount in dollars]
    return "\n".join(lines) + "\n"
