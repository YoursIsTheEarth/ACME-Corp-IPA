from pathlib import Path

import pypdfium2 as pdfium
import pytest

from acme.ingestion import ingest
from acme.ingestion.router import detect_format
from acme.models import FindingCode, Severity

INVOICES = Path(__file__).resolve().parents[3] / "data" / "invoices"

EXPECTED = {
    "invoice_1001.txt": "txt", "invoice_1002.txt": "txt", "invoice_1003.txt": "txt",
    "invoice_1004.json": "json", "invoice_1004_revised.json": "json", "invoice_1005.json": "json",
    "invoice_1006.csv": "csv", "invoice_1007.csv": "csv", "invoice_1008.txt": "email",
    "invoice_1009.json": "json", "invoice_1010.txt": "txt", "invoice_1011.pdf": "pdf",
    "invoice_1011.txt": "txt", "invoice_1012.pdf": "pdf", "invoice_1012.txt": "txt",
    "invoice_1013.json": "json", "invoice_1013.pdf": "pdf", "invoice_1014.xml": "xml",
    "invoice_1015.csv": "csv", "invoice_1016.json": "json",
}


def test_expectations_cover_every_sample_file():
    assert sorted(p.name for p in INVOICES.iterdir()) == sorted(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_detect_format(name):
    assert detect_format(INVOICES / name) == EXPECTED[name]


def test_content_wins_over_extension(tmp_path):
    (tmp_path / "a.txt").write_text('{"invoice_number": "1"}')
    (tmp_path / "b.csv").write_text("<?xml version='1.0'?><invoice/>")
    (tmp_path / "c.bin").write_bytes((INVOICES / "invoice_1011.pdf").read_bytes())
    (tmp_path / "d.eml").write_text("Vendor: X\nTotal: $1.00\n")
    assert [detect_format(tmp_path / n) for n in ("a.txt", "b.csv", "c.bin", "d.eml")] == \
        ["json", "xml", "pdf", "email"]


def _blank_pdf(path: Path) -> Path:
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(612, 792)
    pdf.save(path)
    return path


@pytest.mark.parametrize("name, content, cause", [
    ("empty.txt", b"", "empty file"),
    ("invoice.docx", b"PK\x03\x04 not an invoice", "unsupported file type '.docx'"),
    ("bad.json", b'{"invoice_number": "INV-1", ', "json parse error"),
    ("bad.csv", b"field,value\nquantity,5\n", "csv parse error"),
    ("bad.xml", b"<?xml version='1.0'?><invoice><header>", "xml parse error"),
    ("corrupt.pdf", b"%PDF-1.7 garbage", "unreadable pdf"),
    ("blank.pdf", None, "no text layer"),
])
def test_unreadable_files_fail_closed(db, tmp_path, name, content, cause):
    path = tmp_path / name
    _blank_pdf(path) if content is None else path.write_bytes(content)
    result = ingest(path, run_id="r-bad")
    assert result.extracted is None
    [finding] = result.findings
    assert finding.code == FindingCode.EXTRACTION_FAILED and finding.severity == Severity.CRITICAL
    assert cause in finding.evidence["cause"]
    assert db.execute("SELECT count(*) FROM llm_calls").fetchone()[0] == 0


def test_empty_file_evidence(db, tmp_path):
    (tmp_path / "empty.txt").write_bytes(b"")
    assert ingest(tmp_path / "empty.txt").findings[0].evidence == {"cause": "empty file"}


def test_missing_file_fails_closed(db, tmp_path):
    result = ingest(tmp_path / "nope.json")
    assert result.findings[0].code == FindingCode.EXTRACTION_FAILED
