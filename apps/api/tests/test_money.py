from decimal import Decimal

import pytest

from costura.spend.money import (
    MoneyError,
    minor_to_major,
    split_proportionally,
    to_cents,
    to_storage,
)


def test_cents_string_converts_to_major_units_exactly() -> None:
    assert minor_to_major("123.78912", "USD") == Decimal("1.2378912")


def test_integer_cents_and_zero() -> None:
    assert minor_to_major("250", "usd") == Decimal("2.50")
    assert minor_to_major("0", "USD") == Decimal("0")


def test_no_rounding_before_summation() -> None:
    parts = ["0.333", "0.333", "0.334"]
    total = sum((minor_to_major(p, "USD") for p in parts), Decimal("0"))

    assert total == Decimal("0.01")
    assert sum((to_cents(minor_to_major(p, "USD")) for p in parts), Decimal("0")) == Decimal("0")


def test_to_cents_rounds_half_up() -> None:
    assert to_cents(Decimal("1.005")) == Decimal("1.01")
    assert to_cents(Decimal("1.004999")) == Decimal("1.00")


def test_to_storage_matches_numeric_20_8() -> None:
    assert to_storage(Decimal("1.2378912")) == Decimal("1.23789120")
    assert to_storage(Decimal("1.123456789")) == Decimal("1.12345679")


@pytest.mark.parametrize("amount", ["abc", "", "NaN", "Infinity"])
def test_invalid_amount_raises(amount: str) -> None:
    with pytest.raises(MoneyError):
        minor_to_major(amount, "USD")


def test_unknown_currency_raises() -> None:
    with pytest.raises(MoneyError):
        minor_to_major("100", "JPY")


def test_split_three_ways_sums_exactly() -> None:
    parts = split_proportionally(Decimal("0.01"), [1, 1, 1])

    assert sum(parts) == Decimal("0.01")
    assert parts == [Decimal("0.00333334"), Decimal("0.00333333"), Decimal("0.00333333")]


def test_split_follows_weights_and_keeps_storage_precision() -> None:
    parts = split_proportionally(Decimal("1.2378912"), [1000, 10])

    assert sum(parts) == Decimal("1.2378912")
    assert parts[0] == Decimal("1.22563485")
    assert parts[1] == Decimal("0.01225635")
    assert all(part == part.quantize(Decimal("0.00000001")) for part in parts)


def test_split_zero_weight_gets_nothing_and_negative_total_is_mirrored() -> None:
    assert split_proportionally(Decimal("5"), [0, 3]) == [Decimal("0"), Decimal("5")]
    assert split_proportionally(Decimal("-0.03"), [1, 2]) == [
        Decimal("-0.01"),
        Decimal("-0.02"),
    ]


def test_split_rejects_bad_weights() -> None:
    with pytest.raises(MoneyError):
        split_proportionally(Decimal("1"), [0, 0])
    with pytest.raises(MoneyError):
        split_proportionally(Decimal("1"), [1, -1])
