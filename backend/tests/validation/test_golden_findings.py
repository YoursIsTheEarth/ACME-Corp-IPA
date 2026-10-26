"""Deterministic checks over all 20 golden files, in sorted filename order (tasks 2.6, 6.5)."""

import pytest

from acme.models import Severity
from acme.validation import ValidationContext, run_checks
from golden_invoices import EXPECTED_OUTCOME, GOLDEN, GOLDEN_FILES, KEY_CODES, assessed, record_processed


@pytest.fixture
def golden_findings(seeded_db):
    """Each file validated against the processed_invoices rows of the files before it, with the fake
    model's address verdict (the deterministic checks read it; they never call the LLM)."""
    results = {}
    for name in GOLDEN_FILES:
        invoice = GOLDEN[name]
        results[name] = run_checks(invoice, assessed(ValidationContext.load(seeded_db), invoice))
        record_processed(seeded_db, invoice, EXPECTED_OUTCOME[name], f"r-{name}")
    return results


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_key_finding_codes(golden_findings, name):
    found = {f.code.value for f in golden_findings[name]}
    assert KEY_CODES[name] <= found, name


@pytest.mark.parametrize("name", [n for n, outcome in EXPECTED_OUTCOME.items() if outcome == "APPROVE"])
def test_approved_files_have_no_blocking_findings(golden_findings, name):
    assert [f.code for f in golden_findings[name] if f.severity != Severity.INFO] == []


def test_1010_only_blocking_finding_is_price_variance(golden_findings):
    assert [f.code.value for f in golden_findings["invoice_1010.txt"]] == ["PRICE_VARIANCE"]
