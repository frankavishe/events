"""Money helpers. All amounts are Decimal TZS with 2 decimal places; floats are rejected."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
MONEY_MAX_DIGITS = 12
MONEY_DECIMAL_PLACES = 2


def to_money(value: Decimal | int | str) -> Decimal:
    """Convert to Decimal rounded half-up to 2 dp. Floats raise TypeError (precision loss)."""
    if isinstance(value, float):
        raise TypeError("Money must not be a float; use Decimal or str.")
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def round_money(value: Decimal | int | str) -> Decimal:
    """Round half-up (not banker's rounding) to 2 decimal places."""
    return to_money(value)


def format_tzs(value: Decimal | int | str) -> str:
    """Human format: `TZS 15,000`, or `TZS 1,234,567.50` when there are cents."""
    amount = to_money(value)
    if amount == amount.to_integral_value():
        return f"TZS {amount:,.0f}"
    return f"TZS {amount:,.2f}"
