from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from acme.ingestion import ExtractedInvoice, ingest
from acme.models import FindingCode, Severity
from acme.normalization import normalize
from acme.normalization.fx import convert_currency
from acme.settings import get_settings

INVOICES = Path(__file__).resolve().parents[3] / "data" / "invoices"


def test_fx_rates_default_and_env_override(monkeypatch):
    assert get_settings().fx_rates == {"EUR": Decimal("1.08")}
    monkeypatch.setenv("FX_RATES", '{"EUR": "1.10", "GBP": "1.27"}')
    get_settings.cache_clear()
    assert get_settings().fx_rates == {"EUR": Decimal("1.10"), "GBP": Decimal("1.27")}


def _1014():
    return normalize(ingest(INVOICES / "invoice_1014.xml").extracted)


def test_euro_invoice_converted(seeded_db):
    invoice, findings = _1014()
    rate = get_settings().fx_rates["EUR"]
    assert invoice.total == (Decimal("4125.00") * rate).quantize(Decimal("0.01"), ROUND_HALF_UP) == Decimal("4455.00")
    assert (invoice.currency, invoice.original_currency, invoice.original_total) == ("USD", "EUR", Decimal("4125.00"))
    assert [i.unit_price for i in invoice.line_items] == [Decimal("243.00"), Decimal("513.00")]
    assert (invoice.subtotal, invoice.tax) == (Decimal("4050.00"), Decimal("405.00"))
    [finding] = findings
    assert finding.code == FindingCode.CURRENCY_CONVERTED and finding.severity == Severity.INFO
    assert finding.evidence == {"currency": "EUR", "rate": "1.08", "original_total": "4125.00",
                                "usd_total": "4455.00"}


def test_configured_rate_is_used(seeded_db, monkeypatch):
    monkeypatch.setenv("FX_RATES", '{"EUR": "1.10"}')
    get_settings.cache_clear()
    invoice, _ = _1014()
    assert invoice.total == Decimal("4537.50")


def test_unsupported_currency_not_converted(seeded_db):
    invoice, findings = normalize(ExtractedInvoice(invoice_number="9", currency="gbp", total="100.00"))
    assert (invoice.currency, invoice.total, invoice.original_currency, invoice.original_total) == \
        ("GBP", Decimal("100.00"), None, None)
    [finding] = findings
    assert finding.code == FindingCode.CURRENCY_UNSUPPORTED and finding.severity == Severity.WARNING
    assert finding.evidence == {"currency": "GBP"}


def test_usd_and_missing_currency_unchanged(seeded_db):
    for currency in ("USD", None):
        invoice, findings = normalize(ExtractedInvoice(invoice_number="9", currency=currency, total="100.00"))
        assert (invoice.currency, invoice.total, invoice.original_currency) == ("USD", Decimal("100.00"), None)
        assert findings == []


def test_convert_currency_directly(seeded_db):
    invoice, _ = normalize(ExtractedInvoice(invoice_number="9", currency="EUR", total="10.00"))
    again, findings = convert_currency(invoice)  # already USD: no double conversion
    assert again.total == invoice.total and findings == []
