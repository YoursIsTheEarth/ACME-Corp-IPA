"""Upload intake (F27), invoice list views (F23-F25), detail and original file (F30), audit CSV (F35)."""

import asyncio
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from acme import workflow
from acme.api import queries
from acme.api.csv_export import csv_response
from acme.api.deps import db, services
from acme.db import connect
from acme.payments._store import immediate
from acme.settings import get_settings

router = APIRouter(tags=["invoices"])

CHUNK = 1024 * 1024
AUDIT_CSV_COLUMNS = ("id", "file_name", "invoice_number", "vendor", "amount_usd", "final_status", "decided_by",
                     "key_findings", "findings_count", "uploaded_at", "completed_at", "processing_s")


async def _store(upload: UploadFile, target: Path, max_bytes: int) -> tuple[int, bool]:
    """Copy the upload to `target` in chunks, stopping once it passes `max_bytes`. Returns (size, too_big)."""
    size = 0
    with target.open("wb") as out:
        while chunk := await upload.read(CHUNK):
            size += len(chunk)
            if size > max_bytes:
                return size, True
            out.write(chunk)
    return size, False


def _create_runs(accepted: list[tuple[str, Path]], upload_dir: Path) -> list[str]:
    """One `invoice_runs` row per file (via `workflow.create_run`), files moved to `UPLOAD_DIR/<run_id>/`."""
    conn = connect()
    try:
        created = []
        for name, temp in accepted:
            run_id = workflow.create_run(name, stored_path=temp, conn=conn)
            final = upload_dir / run_id / name
            final.parent.mkdir(parents=True, exist_ok=True)
            temp.replace(final)
            created.append((run_id, final))
        with immediate(conn):
            conn.executemany("UPDATE invoice_runs SET stored_path = ? WHERE id = ?",
                             [(str(path), run_id) for run_id, path in created])
        return [run_id for run_id, _ in created]
    finally:
        conn.close()


@router.post("/api/invoices", status_code=202)
async def upload_invoices(request: Request, files: list[UploadFile] | None = File(None),
                          file: list[UploadFile] | None = File(None)) -> dict[str, Any]:
    """Multipart upload of one or more files (field `files`; `file` also accepted). Each file is judged alone."""
    uploads = [*(files or []), *(file or [])]
    if not uploads:
        raise HTTPException(422, "No files in the request; send them as multipart field 'files'.")
    settings = get_settings()
    upload_dir = settings.upload_dir.resolve()
    incoming = upload_dir / ".incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    max_mb = settings.upload_max_bytes / (1024 * 1024)

    results: list[dict[str, Any]] = []
    accepted: list[tuple[int, str, Path]] = []
    for upload in uploads:
        name = Path(upload.filename or "").name
        entry: dict[str, Any] = {"id": None, "file_name": name, "status": "rejected", "size": None, "error": None}
        results.append(entry)
        if not name or Path(name).suffix.lower() not in settings.allowed_upload_extensions:
            entry["error"] = f"Unsupported file type; allowed: {', '.join(settings.allowed_upload_extensions)}"
            continue
        temp = incoming / uuid.uuid4().hex
        size, too_big = await _store(upload, temp, settings.upload_max_bytes)
        entry["size"] = size
        if too_big or size == 0:
            temp.unlink(missing_ok=True)
            entry["error"] = f"File is over {max_mb:g} MB" if too_big else "Empty file"
            continue
        accepted.append((len(results) - 1, name, temp))

    run_ids = await asyncio.to_thread(_create_runs, [(name, temp) for _, name, temp in accepted], upload_dir)
    svc = services(request)
    for (index, _, _), run_id in zip(accepted, run_ids):
        results[index] |= {"id": run_id, "status": "Uploaded"}
    with db() as conn:
        rows = {run_id: queries.run_summary(conn, run_id) for run_id in run_ids}
    for run_id in run_ids:
        svc.bus.publish("invoice.created", {"run_id": run_id, "stage": "Uploaded", "status": "Uploaded",
                                            "invoice": rows[run_id]})
        svc.worker.submit("process", run_id)
    return {"files": results, "accepted": len(run_ids), "rejected": len(results) - len(run_ids),
            "server_time": queries.server_time()}


@router.get("/api/invoices")
def list_invoices(view: Literal["queue", "audit", "review"], status: str | None = None,
                  date_from: date | None = None, date_to: date | None = None,
                  search: str | None = None) -> dict[str, Any]:
    """`view=queue` (unresolved), `audit` (resolved; filters `status`, `date_from`, `date_to`, `search`),
    or `review` (held for a person). Any other view is 422."""
    with db() as conn:
        if view == "queue":
            rows = queries.queue_view(conn)
        elif view == "review":
            rows = queries.review_view(conn)
        else:
            rows = queries.audit_view(conn, status, date_from, date_to, search)
    return {"view": view, "rows": rows, "count": len(rows), "server_time": queries.server_time()}


@router.get("/api/invoices.csv", response_class=StreamingResponse)
def export_invoices(status: str | None = None, date_from: date | None = None, date_to: date | None = None,
                    search: str | None = None) -> StreamingResponse:
    """The audit view as CSV, with the same filters as `GET /api/invoices?view=audit`."""
    with db() as conn:
        rows = queries.audit_view(conn, status, date_from, date_to, search)
    for row in rows:
        row["key_findings"] = ";".join(f["code"] for f in row["key_findings"])
    return csv_response("invoices.csv", AUDIT_CSV_COLUMNS, rows)


@router.get("/api/invoices/{run_id}")
def invoice_detail(run_id: str) -> dict[str, Any]:
    """Full record: extracted fields, findings, drafts and critiques, reviews, payments, timeline."""
    with db() as conn:
        detail = queries.invoice_detail(conn, run_id)
    if detail is None:
        raise HTTPException(404, f"Invoice {run_id} not found")
    return detail


@router.get("/api/invoices/{run_id}/file", response_class=FileResponse)
def invoice_file(run_id: str) -> FileResponse:
    """The original uploaded bytes, with a content type matching the file."""
    with db() as conn:
        row = queries.run_exists(conn, run_id)
    path = Path(row["stored_path"]) if row is not None and row["stored_path"] else None
    if path is None or not path.is_file():
        raise HTTPException(404, f"File for invoice {run_id} not found")
    return FileResponse(path, media_type=queries.content_type(row["file_name"]), filename=row["file_name"],
                        content_disposition_type="inline")
