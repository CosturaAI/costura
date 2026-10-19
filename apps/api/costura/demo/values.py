"""The arithmetic behind every sample amount: pure functions of the dataset version, the day
and the principal, so two builds on different days agree on every day both cover.

A principal's day is `base x weekday x growth x noise x story`. The weekday factor gives the
week its shape (quiet weekends), growth compounds monthly from `GROWTH_REFERENCE`, the noise
is a hash of `(version, day, provider, account, principal)` and stays inside the detector's
bounds, and the story multiplies the days of a scripted event."""

import hashlib
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# A Monday. Story cycles count from it, so a cycle day always falls on the same weekday.
EPOCH = date(2024, 1, 1)
CYCLE_DAYS = 28

# Monday first. Weekends run at under a third of a weekday, as teams that ship on weekdays do.
WEEKDAY_FACTORS = (
    Decimal("1.00"),
    Decimal("1.06"),
    Decimal("1.09"),
    Decimal("1.04"),
    Decimal("0.93"),
    Decimal("0.31"),
    Decimal("0.27"),
)
MONTHLY_GROWTH = 0.035
GROWTH_REFERENCE = date(2026, 1, 1)
DAYS_PER_MONTH = 30.4375
# Half-width of the daily noise: well inside the detector's 20 percent relative margin.
NOISE = Decimal("0.05")
MICRO = Decimal("0.000001")
CENT_FRACTION = Decimal("0.00001")


def unit(*parts: object) -> Decimal:
    """A stable value in [0, 1) for `parts`."""
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).digest()
    return (Decimal(int.from_bytes(digest[:8], "big")) / Decimal(2**64)).quantize(MICRO)


def noise(version: int, day: date, provider: str, account: str, principal: str) -> Decimal:
    return Decimal("1") - NOISE + 2 * NOISE * unit(version, day, provider, account, principal)


def growth(day: date) -> Decimal:
    months = (day - GROWTH_REFERENCE).days / DAYS_PER_MONTH
    return Decimal(str(round((1 + MONTHLY_GROWTH) ** months, 6)))


def weekday_factor(day: date) -> Decimal:
    return WEEKDAY_FACTORS[day.weekday()]


def cycle_day(day: date) -> int:
    return (day - EPOCH).days % CYCLE_DAYS


def ramp(day: date, start: date | None, days: int) -> Decimal:
    """0 before `start`, rising linearly to 1 over `days`: a new member finding their feet."""
    if start is None or days <= 0:
        return Decimal("1")
    elapsed = (day - start).days
    if elapsed < 0:
        return Decimal("0")
    return min(Decimal("1"), Decimal(elapsed + 1) / Decimal(days))


def micro(value: Decimal) -> Decimal:
    return value.quantize(MICRO, rounding=ROUND_HALF_UP)


def cents(value: Decimal) -> Decimal:
    """USD to provider minor units with the precision Anthropic reports them."""
    return (value * 100).quantize(CENT_FRACTION, rounding=ROUND_HALF_UP)
