from datetime import UTC, datetime
from decimal import Decimal

import pytest

from costura.providers.anthropic.normalize import cost_lines_from_payload, usage_lines_from_payload
from costura.providers.lines import NormalizeError, aggregate_cost_lines, aggregate_usage_lines
from tests.conftest import load_fixture

# Hand-computed from the fixture amounts (cents):
# 123.78912 + 250.5 + 1000 + 76.21088 + 10.5 + 0.5 + 5000 = 6461.5 cents = 64.615 USD.
COST_FIXTURE_TOTAL = Decimal("64.615")
COST_FIXTURE_RESULTS = 7
COST_FIXTURE_DISTINCT_KEYS = 6

USAGE_FIXTURE_TOTALS = {
    "uncached_input_tokens": 1000 + 10 + 20000,
    "cache_creation_5m_tokens": 200,
    "cache_creation_1h_tokens": 50 + 1000,
    "cache_read_tokens": 3000 + 500 + 100000,
    "output_tokens": 400 + 5 + 8000,
    "web_search_requests": 2,
}


def _cost_lines():
    page1 = cost_lines_from_payload(load_fixture("cost_report_page1.json"))
    page2 = cost_lines_from_payload(load_fixture("cost_report_page2.json"))
    return page1 + page2


def _usage_lines():
    page1 = usage_lines_from_payload(load_fixture("usage_report_page1.json"))
    page2 = usage_lines_from_payload(load_fixture("usage_report_page2.json"))
    return page1 + page2


def test_cost_result_keeps_every_dimension() -> None:
    line = _cost_lines()[0]

    assert line.provider == "anthropic"
    assert line.period_start == datetime(2026, 8, 1, tzinfo=UTC)
    assert line.period_end == datetime(2026, 8, 2, tzinfo=UTC)
    assert line.workspace_id is None
    assert line.description == "Claude Opus 5 Usage - Input Tokens"
    assert line.cost_type == "tokens"
    assert line.model == "claude-opus-5"
    assert line.token_type == "uncached_input_tokens"
    assert line.service_tier == "standard"
    assert line.context_window == "0-200k"
    assert line.inference_geo == "global"
    assert line.amount == Decimal("1.2378912")
    assert line.currency == "USD"
    assert line.raw_amount_minor == "123.78912"


def test_non_token_cost_has_null_token_dimensions() -> None:
    web_search = next(line for line in _cost_lines() if line.cost_type == "web_search")

    assert web_search.workspace_id == "wrkspc_redacted_a"
    assert (web_search.model, web_search.token_type, web_search.service_tier) == (None, None, None)
    assert web_search.amount == Decimal("10")


def test_cost_fixture_total_matches_hand_computed_value() -> None:
    lines = _cost_lines()

    assert len(lines) == COST_FIXTURE_RESULTS
    assert sum((line.amount for line in lines), Decimal("0")) == COST_FIXTURE_TOTAL


def test_duplicate_keys_within_a_response_are_summed() -> None:
    aggregated = aggregate_cost_lines(_cost_lines())

    assert len(aggregated) == COST_FIXTURE_DISTINCT_KEYS
    assert sum((line.amount for line in aggregated), Decimal("0")) == COST_FIXTURE_TOTAL
    merged = next(line for line in aggregated if line.service_tier == "batch")
    assert merged.amount == Decimal("0.11")
    assert merged.raw_amount_minor == "10.5+0.5"


def test_usage_cache_creation_is_split_into_5m_and_1h() -> None:
    line = _usage_lines()[0]

    assert line.api_key_id == "apikey_redacted_1"
    assert line.workspace_id is None
    assert (line.model, line.service_tier) == ("claude-opus-5", "standard")
    assert line.uncached_input_tokens == 1000
    assert line.cache_creation_5m_tokens == 200
    assert line.cache_creation_1h_tokens == 50
    assert line.cache_read_tokens == 3000
    assert line.output_tokens == 400
    assert line.web_search_requests == 2


def test_playground_usage_keeps_null_api_key_and_account() -> None:
    no_key = [line for line in _usage_lines() if line.api_key_id is None]

    assert len(no_key) == 2
    playground = [line for line in no_key if line.account_id is None]
    assert len(playground) == 1
    assert playground[0].output_tokens == 5
    oauth = [line for line in no_key if line.account_id == "user_redacted_alice"]
    assert len(oauth) == 1
    assert (oauth[0].workspace_id, oauth[0].cache_read_tokens) == ("wrkspc_redacted_a", 100000)


def test_usage_carries_pricing_grain() -> None:
    lines = _usage_lines()

    assert (lines[0].context_window, lines[0].inference_geo) == ("0-200k", "global")
    batch = next(line for line in lines if line.api_key_id == "apikey_redacted_2")
    assert (batch.context_window, batch.inference_geo) == ("200k-1M", "us")


def test_usage_lines_differing_only_by_context_window_stay_distinct() -> None:
    payload = load_fixture("usage_report_page1.json")
    long_context = dict(payload["data"][0]["results"][0])
    long_context["context_window"] = "200k-1M"
    payload["data"][0]["results"].append(long_context)

    aggregated = aggregate_usage_lines(usage_lines_from_payload(payload))

    keyed = [line for line in aggregated if line.api_key_id == "apikey_redacted_1"]
    assert sorted(line.context_window or "" for line in keyed) == ["0-200k", "200k-1M"]
    assert all(line.uncached_input_tokens == 1000 for line in keyed)


def test_usage_fixture_totals() -> None:
    aggregated = aggregate_usage_lines(_usage_lines())

    assert len(aggregated) == 4
    for name, expected in USAGE_FIXTURE_TOTALS.items():
        assert sum(getattr(line, name) for line in aggregated) == expected, name


def test_usage_lines_with_same_key_are_summed() -> None:
    payload = load_fixture("usage_report_page1.json")
    payload["data"][0]["results"].append(dict(payload["data"][0]["results"][0]))

    aggregated = aggregate_usage_lines(usage_lines_from_payload(payload))

    assert len(aggregated) == 2
    keyed = next(line for line in aggregated if line.api_key_id == "apikey_redacted_1")
    assert keyed.uncached_input_tokens == 2000
    assert keyed.web_search_requests == 4


def test_missing_required_field_raises() -> None:
    payload = load_fixture("cost_report_page1.json")
    payload["data"][0]["results"][0]["cost_type"] = None

    with pytest.raises(NormalizeError, match="cost_type"):
        cost_lines_from_payload(payload)
