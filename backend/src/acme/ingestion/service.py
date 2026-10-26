"""`ingest(path)`: the single ingestion entry point (F1-F4). It never raises for bad input."""

from pathlib import Path

from acme.ingestion import offline  # noqa: F401  (registers the offline extraction handler)
from acme.ingestion.llm_extract import check_line_sum, llm_extract
from acme.ingestion.parsers import parse_csv, parse_json, parse_xml
from acme.ingestion.pdf import pdf_to_text
from acme.ingestion.router import detect_format
from acme.ingestion.schema import ExtractedInvoice, IngestionResult
from acme.logging import audit, run_context, run_id_var
from acme.models import Finding, FindingCode
from acme.settings import get_settings

AGENT = "ingestion"
_PARSERS = {"json": parse_json, "csv": parse_csv, "xml": parse_xml}


def extraction_failed(cause: str, **evidence) -> Finding:
    code = FindingCode.EXTRACTION_FAILED
    return Finding(code=code, severity=code.severity, message=f"Extraction failed: {cause}",
                   evidence={"cause": cause, **evidence})


def _attempt(run_id: str | None, attempt: int, fmt: str | None, outcome: str) -> None:
    audit(run_id, AGENT, "extraction_attempt", {"attempt": attempt, "outcome": outcome, "format": fmt})


def _read(path: Path, fmt: str) -> str:
    if fmt == "pdf":
        return pdf_to_text(path)
    return path.read_bytes().decode("utf-8-sig", errors="replace")


def _extract_with_llm(run_id: str | None, text: str, fmt: str) -> tuple[ExtractedInvoice | None, int, str | None]:
    """F4 loop: up to `extraction_max_retries` retries, each fed the previous error."""
    error = None
    attempts = get_settings().extraction_max_retries + 1
    for attempt in range(1, attempts + 1):
        try:
            extracted = llm_extract(text, error)
            check_line_sum(extracted)
        except Exception as exc:  # schema, arithmetic, or provider failure: retry, then fail closed
            error = f"{type(exc).__name__}: {exc}"
            _attempt(run_id, attempt, fmt, error)
            continue
        _attempt(run_id, attempt, fmt, "accepted")
        return extracted, attempt, None
    return None, attempts, error


def ingest(path: str | Path, run_id: str | None = None) -> IngestionResult:
    """Turn any invoice file into raw text, a source format, and an `ExtractedInvoice`.

    On failure `extracted` is None and `findings` holds one CRITICAL EXTRACTION_FAILED.
    `run_id` defaults to the current `run_context`.
    """
    path = Path(path)
    run_id = run_id if run_id is not None else run_id_var.get()
    with run_context(run_id, agent=AGENT):
        fmt = None
        try:
            if path.stat().st_size == 0:
                cause = "empty file"
            elif (fmt := detect_format(path)) is None:
                cause = f"unsupported file type {path.suffix or '(none)'!r}"
            else:
                cause = None
                text = _read(path, fmt)
        except Exception as exc:  # unreadable, corrupt PDF, no text layer
            cause = f"unreadable {fmt or 'file'}: {exc}"
        if cause is not None:
            _attempt(run_id, 1, fmt, cause)
            return IngestionResult(source_format=fmt, findings=[extraction_failed(cause)], attempts=1)

        if fmt in _PARSERS:
            try:
                extracted = _PARSERS[fmt](text)
            except Exception as exc:  # malformed JSON/CSV/XML or schema mismatch
                cause = f"{fmt} parse error: {type(exc).__name__}: {exc}"
                _attempt(run_id, 1, fmt, cause)
                return IngestionResult(raw_text=text, source_format=fmt,
                                       findings=[extraction_failed(cause)], attempts=1)
            _attempt(run_id, 1, fmt, "accepted")
            return IngestionResult(raw_text=text, source_format=fmt, extracted=extracted, attempts=1)

        extracted, attempts, error = _extract_with_llm(run_id, text, fmt)
        findings = [] if extracted else [
            extraction_failed("extraction did not pass validation", attempts=attempts, last_error=error)
        ]
        return IngestionResult(raw_text=text, source_format=fmt, extracted=extracted,
                               findings=findings, attempts=attempts)
