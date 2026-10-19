from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

# Minor-unit exponent per ISO 4217 currency. Providers report USD; the table exists so a
# non-decimal currency is a loud failure instead of a silent /100.
MINOR_UNIT_EXPONENT: dict[str, int] = {"USD": 2, "EUR": 2, "GBP": 2}

# Storage precision of spend_cost_lines.amount (numeric(20, 8)).
STORAGE_EXPONENT = Decimal("0.00000001")
CENT = Decimal("0.01")
# One percentage point, for shares and ratios shown to a person.
PERCENT = Decimal("0.01")


class MoneyError(ValueError):
    """The amount string or the currency cannot be interpreted."""


def minor_to_major(amount: str, currency: str) -> Decimal:
    """Convert a provider amount expressed in minor units (cents) to major units.

    The input is the exact string received from the provider; no float conversion and no
    rounding happen here. `"123.78912"` USD -> `Decimal("1.2378912")`.
    """
    try:
        exponent = MINOR_UNIT_EXPONENT[currency.upper()]
    except KeyError as exc:
        raise MoneyError(f"unsupported currency: {currency!r}") from exc
    try:
        value = Decimal(amount)
    except (InvalidOperation, TypeError) as exc:
        raise MoneyError(f"invalid amount: {amount!r}") from exc
    if not value.is_finite():
        raise MoneyError(f"invalid amount: {amount!r}")
    return value.scaleb(-exponent)


def to_storage(value: Decimal) -> Decimal:
    """Quantize to the column precision. Applied once, right before the write."""
    return value.quantize(STORAGE_EXPONENT)


def to_cents(value: Decimal) -> Decimal:
    """Round to the cent for display. Never used before summation or comparison."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def to_percent(value: Decimal) -> Decimal:
    """Round a percentage to two decimals for display."""
    return value.quantize(PERCENT, rounding=ROUND_HALF_UP)


def within_cent(delta: Decimal) -> bool:
    """Whether an exact monetary delta is inside the inclusive one-cent tolerance."""
    return abs(delta) <= CENT


def split_proportionally(total: Decimal, weights: list[int]) -> list[Decimal]:
    """Split `total` across `weights` so the parts are quantized to storage precision and
    sum to `total` exactly (largest-remainder method).

    Each part starts at floor(total * w / sum(w)); the units left by flooring go one each
    to the parts with the largest discarded remainder, ties broken by position.
    """
    if any(weight < 0 for weight in weights):
        raise MoneyError("weights must be non-negative")
    weight_sum = sum(weights)
    if weight_sum <= 0:
        raise MoneyError("weights must sum to a positive number")
    total = to_storage(total)
    if total < 0:
        return [-part for part in split_proportionally(-total, weights)]
    exact = [total * weight / weight_sum for weight in weights]
    floored = [value.quantize(STORAGE_EXPONENT, rounding=ROUND_DOWN) for value in exact]
    shortfall = int(((total - sum(floored, Decimal("0"))) / STORAGE_EXPONENT).to_integral_value())
    by_remainder = sorted(
        range(len(weights)), key=lambda i: (floored[i] - exact[i], i)
    )  # most negative first = largest remainder
    parts = list(floored)
    for index in by_remainder[:shortfall]:
        parts[index] += STORAGE_EXPONENT
    return parts
