"""Currency conversion to USD at fixed configured rates (F7, design D11)."""

from decimal import ROUND_HALF_UP, Decimal

from acme.models import Finding, FindingCode, Invoice
from acme.normalization.cleaners import CENT
from acme.settings import get_settings


def _usd(amount: Decimal | None, rate: Decimal) -> Decimal | None:
    return None if amount is None else (amount * rate).quantize(CENT, rounding=ROUND_HALF_UP)


def convert_currency(invoice: Invoice, rates: dict[str, Decimal] | None = None) -> tuple[Invoice, list[Finding]]:
    """Convert a non-USD invoice to USD, keeping `original_currency`/`original_total`.

    Every money field is converted (not only the total and unit prices) so the invoice's
    own arithmetic still holds for validation. No rate -> unchanged + WARNING CURRENCY_UNSUPPORTED.
    """
    currency = (invoice.currency or "USD").strip().upper()
    if currency == "USD":
        return invoice.model_copy(update={"currency": "USD"}), []
    rates = get_settings().fx_rates if rates is None else rates
    rate = {k.upper(): v for k, v in rates.items()}.get(currency)
    if rate is None:
        code = FindingCode.CURRENCY_UNSUPPORTED
        return invoice, [Finding(code=code, severity=code.severity,
                                 message=f"No exchange rate configured for {currency}; amounts not converted",
                                 evidence={"currency": currency})]
    rate = Decimal(rate)
    converted = invoice.model_copy(update={
        "currency": "USD",
        "original_currency": currency,
        "original_total": invoice.total,
        "subtotal": _usd(invoice.subtotal, rate),
        "tax": _usd(invoice.tax, rate),
        "shipping": _usd(invoice.shipping, rate),
        "total": _usd(invoice.total, rate),
        "line_items": [
            item.model_copy(update={"unit_price": _usd(item.unit_price, rate), "amount": _usd(item.amount, rate)})
            for item in invoice.line_items
        ],
    })
    code = FindingCode.CURRENCY_CONVERTED
    return converted, [Finding(
        code=code, severity=code.severity,
        message=f"Converted {invoice.total} {currency} to {converted.total} USD at {rate}",
        evidence={"currency": currency, "rate": str(rate), "original_total": str(invoice.total),
                  "usd_total": str(converted.total)},
    )]
