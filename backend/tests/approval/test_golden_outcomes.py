"""Task 7.1: ingest -> normalize -> validate -> approve, with the test fake model, over all 26 files in sorted order."""

from pathlib import Path

import pytest

from acme.approval import apply_policy, run_approval
from acme.ingestion import ingest
from acme.models import InvoiceState
from acme.normalization import normalize
from acme.validation import ValidationContext, run_validation
from golden_invoices import EXPECTED_OUTCOME, GOLDEN_FILES, KEY_CODES, record_processed

INVOICES = Path(__file__).resolve().parents[3] / "data" / "invoices"


@pytest.fixture
def results(seeded_db):
    out = {}
    for name in GOLDEN_FILES:
        run_id = f"r-{name}"
        invoice, findings = normalize(ingest(INVOICES / name, run_id=run_id).extracted, conn=seeded_db, run_id=run_id)
        state = InvoiceState(run_id=run_id, file_path=str(INVOICES / name), invoice=invoice, findings=findings)
        state = run_approval(run_validation(state, ValidationContext.load(seeded_db)))
        floor = apply_policy(state.invoice, state.findings, state.revision_context).floor
        out[name] = (floor, state)
        record_processed(seeded_db, invoice, state.decision.outcome, run_id)  # disposition stand-in
    return out


def test_floor_and_final_outcomes(results):
    floors = {name: floor.value for name, (floor, _) in results.items()}
    finals = {name: state.decision.outcome.value for name, (_, state) in results.items()}
    assert floors == finals == EXPECTED_OUTCOME
    assert list(finals.values()).count("REJECT") == 12
    assert list(finals.values()).count("NEEDS_REVIEW") == 4


def test_key_finding_codes(results):
    for name, (_, state) in results.items():
        assert KEY_CODES[name] <= {f.code.value for f in state.findings}, name
    assert "CURRENCY_CONVERTED" in {f.code.value for f in results["invoice_1014.xml"][1].findings}


def test_revision_links_unpaid_original(results):
    revision = results["invoice_1004_revised.json"][1].revision_context
    assert revision.original_run_id == "r-invoice_1004.json" and revision.original_outcome == "APPROVE"
    assert not revision.paid


def test_every_decision_has_rationale_and_provenance(results):
    for name, (_, state) in results.items():
        assert state.decision.rationale and state.decision.decided_by == "Auto (rules)", name
