"""Integration: ingest() then normalize() over all 20 sample files in offline mode (task 6.1)."""

from pathlib import Path

import pytest

from acme.ingestion import ingest
from acme.models import FindingCode, Invoice
from acme.normalization import normalize

INVOICES = Path(__file__).resolve().parents[3] / "data" / "invoices"
FILES = sorted(p.name for p in INVOICES.iterdir())


@pytest.fixture
def outcomes(seeded_db):
    results = {}
    for name in FILES:
        ingested = ingest(INVOICES / name, run_id=f"r-{name}")
        if ingested.extracted is None:
            results[name] = (None, ingested.findings)
        else:
            results[name] = normalize(ingested.extracted, run_id=f"r-{name}")
    return results


def test_every_file_yields_an_invoice_or_extraction_failed(outcomes):
    assert len(outcomes) == 20
    for name, (invoice, findings) in outcomes.items():
        assert isinstance(invoice, Invoice) or [f.code for f in findings] == [FindingCode.EXTRACTION_FAILED], name


def test_all_sample_files_extract_offline(outcomes):
    assert all(invoice is not None for invoice, _ in outcomes.values())


def test_only_normalization_finding_is_the_euro_conversion(outcomes):
    flagged = {name: [f.code for f in findings] for name, (_, findings) in outcomes.items() if findings}
    assert flagged == {"invoice_1014.xml": [FindingCode.CURRENCY_CONVERTED]}


def test_1003_relative_due_date(outcomes):
    invoice, _ = outcomes["invoice_1003.txt"]
    assert invoice.due_date is None and invoice.due_date_raw == "yesterday"


def test_invoice_numbers_canonical(outcomes):
    for name, (invoice, _) in outcomes.items():
        assert invoice.invoice_number == f"INV-{name[8:12]}", name
