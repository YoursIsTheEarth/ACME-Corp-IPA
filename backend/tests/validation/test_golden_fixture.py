"""The hand-coded golden invoices equal what ingestion + normalization produce with the test fake model."""

from pathlib import Path

import pytest

from acme.ingestion import ingest
from acme.normalization import normalize
from golden_invoices import GOLDEN_FILES

INVOICES = Path(__file__).resolve().parents[3] / "data" / "invoices"


def test_fixture_covers_all_20_files(golden):
    assert sorted(golden) == GOLDEN_FILES == sorted(p.name for p in INVOICES.iterdir())


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_matches_pipeline_output(seeded_db, golden, name):
    invoice, _ = normalize(ingest(INVOICES / name).extracted, conn=seeded_db)
    assert invoice == golden[name]
