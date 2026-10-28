"""Error branches of the shared provider line helpers.

The happy paths are covered through each provider's normalize tests;
these pin the guards in `costura.providers.lines` that coverage
reported as never run (issue #17).
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from costura.providers.lines import CostLine, NormalizeError, aggregate_cost_lines, parse_timestamp


@pytest.mark.parametrize("value", [123, None, datetime(2026, 8, 1, tzinfo=UTC)])
def test_parse_timestamp_rejects_non_string(value: object) -> None:
    with pytest.raises(NormalizeError, match="is not a string"):
        parse_timestamp(value, field="start_time")


def test_parse_timestamp_rejects_timestamp_without_timezone() -> None:
    with pytest.raises(NormalizeError, match="has no timezone"):
        parse_timestamp("2026-08-01T00:00:00", field="start_time")


def _cost_line(currency: str) -> CostLine:
    return CostLine(
        period_start=datetime(2026, 8, 1, tzinfo=UTC),
        period_end=datetime(2026, 8, 2, tzinfo=UTC),
        workspace_id=None,
        description="Claude Opus 5 Usage - Input Tokens",
        cost_type="tokens",
        model="claude-opus-5",
        token_type="uncached_input_tokens",
        service_tier="standard",
        context_window="0-200k",
        inference_geo="global",
        amount=Decimal("1.5"),
        currency=currency,
        raw_amount_minor="150",
        provider="anthropic",
    )


def test_aggregate_cost_lines_rejects_mixed_currencies_for_one_key() -> None:
    with pytest.raises(NormalizeError, match="mixed currencies for one key"):
        aggregate_cost_lines([_cost_line("USD"), _cost_line("EUR")])
