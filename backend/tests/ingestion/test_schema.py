from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from acme.ingestion import ExtractedInvoice, IngestionResult
from acme.models import Invoice, LineItem


def test_extracted_invoice_subclasses_the_foundation_models():
    assert issubclass(ExtractedInvoice, Invoice)
    assert issubclass(ExtractedInvoice.model_fields["line_items"].annotation.__args__[0], LineItem)


def test_raw_string_dates_and_money_validate():
    inv = ExtractedInvoice(
        invoice_number="Inv #: 1002", invoice_date="26-Jan-2O26", due_date="yesterday",
        line_items=[{"raw_name": "WidgetB", "quantity": 7, "unit_price": "$500", "amount": "$3,500.O0"}],
        subtotal="$9,500.00", tax="$475.00", total="$9,975.00",
    )
    assert inv.invoice_date == "26-Jan-2O26" and inv.due_date == "yesterday"
    assert inv.line_items[0].amount == "$3,500.O0" and inv.line_items[0].sku is None
    assert inv.total == "$9,975.00" and inv.currency is None


def test_typed_values_still_accepted():
    inv = ExtractedInvoice(invoice_number="INV-1", invoice_date=date(2026, 1, 1), total=Decimal("10.00"),
                           revision="R1")
    assert inv.invoice_date == date(2026, 1, 1) and inv.total == Decimal("10.00") and inv.revision == 1


def test_non_numeric_quantity_is_a_schema_error():
    with pytest.raises(ValidationError, match="quantity"):
        ExtractedInvoice(invoice_number="1", total="1", line_items=[{"raw_name": "x", "quantity": "lots"}])


@pytest.mark.parametrize("raw, expected", [("1,200", 1200), ("-1,200", -1200), ("1,234,567", 1234567), (12, 12)])
def test_quantity_thousands_separators_are_ignored(raw, expected):
    inv = ExtractedInvoice(invoice_number="1", total="1", line_items=[{"raw_name": "x", "quantity": raw}])
    assert inv.line_items[0].quantity == expected


@pytest.mark.parametrize("raw", ["twelve", "1,2", "12,00"])
def test_quantity_with_bad_commas_is_still_a_schema_error(raw):
    with pytest.raises(ValidationError, match="quantity"):
        ExtractedInvoice(invoice_number="1", total="1", line_items=[{"raw_name": "x", "quantity": raw}])


def test_ingestion_result_retries():
    assert IngestionResult(attempts=2).retries == 1
    assert IngestionResult().retries == 0
