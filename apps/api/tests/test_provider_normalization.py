"""Scalar parsing shared by all provider normalizers."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from costura.providers.lines import CostLine, NormalizeError, aggregate_cost_lines, parse_timestamp
from costura.providers.normalization import optional_text, rfc3339, unix_seconds


def test_text_parsing() -> None:
    assert optional_text(None, field="name") is None
    assert optional_text("", field="name") is None
    assert optional_text("value", field="name") == "value"
    with pytest.raises(NormalizeError, match="name is not a string"):
        optional_text(3, field="name")


@pytest.mark.parametrize("value", [True, "0", None, []])
def test_unix_timestamp_rejects_wrong_shape(value: object) -> None:
    with pytest.raises(NormalizeError, match="is not Unix"):
        unix_seconds(value, field="at")


def test_unix_timestamps_use_utc_and_reject_overflow() -> None:
    assert unix_seconds(0, field="at") == datetime(1970, 1, 1, tzinfo=UTC)
    with pytest.raises(NormalizeError, match="outside the supported range"):
        unix_seconds(10**30, field="at")


def test_rfc3339_requires_timezone_and_normalizes_to_utc() -> None:
    aware = datetime.fromisoformat("2026-10-10T10:30:00+02:00")
    assert rfc3339(aware) == "2026-10-10T08:30:00Z"
    with pytest.raises(ValueError, match="timezone-aware"):
        rfc3339(datetime(2026, 10, 10))


@pytest.mark.parametrize(
    "value,match",
    [
        (123, "timestamp is not a string"),
        ("2026-10-10T10:30:00", "timestamp has no timezone"),
    ],
)
def test_parse_timestamp_errors(value: object, match: str) -> None:
    with pytest.raises(NormalizeError, match=match):
        parse_timestamp(value, field="timestamp")


def test_aggregate_cost_lines_mixed_currencies() -> None:
    dt = datetime(2026, 1, 1, tzinfo=UTC)
    line1 = CostLine(
        period_start=dt,
        period_end=dt,
        workspace_id=None,
        description="test",
        cost_type="api",
        model=None,
        token_type=None,
        service_tier=None,
        context_window=None,
        inference_geo=None,
        amount=Decimal("1.00"),
        currency="USD",
        raw_amount_minor="100",
        provider="test",
    )
    line2 = CostLine(
        period_start=dt,
        period_end=dt,
        workspace_id=None,
        description="test",
        cost_type="api",
        model=None,
        token_type=None,
        service_tier=None,
        context_window=None,
        inference_geo=None,
        amount=Decimal("1.00"),
        currency="EUR",
        raw_amount_minor="100",
        provider="test",
    )
    with pytest.raises(NormalizeError, match="mixed currencies for one key"):
        aggregate_cost_lines([line1, line2])
