"""Boundary and operator tests for the shared spend filter contract."""

import pytest

from costura.spend.filters import (
    MAX_FILTER_TEXT,
    MAX_FILTER_VALUES,
    MAX_FILTERS,
    FilterClause,
    exact_filter,
    filter_clause,
    filter_matches,
    normalize_filters,
    token_type_matches,
)


@pytest.mark.parametrize(
    "value",
    [
        {"op": "wat", "values": ["x"]},
        {"op": "exists", "values": ["x"]},
        {"op": "is", "values": []},
        {"op": "is", "values": ["a", "b"]},
        {"op": "one_of", "values": ["x"] * (MAX_FILTER_VALUES + 1)},
        {"op": "is", "values": [""]},
        {"op": "is", "values": ["x" * (MAX_FILTER_TEXT + 1)]},
        {"op": "is", "values": [1]},
    ],
)
def test_filter_clause_rejects_invalid_operator_values(value: object) -> None:
    with pytest.raises(ValueError):
        filter_clause(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"op": "is"},
        {"op": "is", "values": ["x"], "extra": True},
        {"op": 1, "values": ["x"]},
        {"op": "is", "values": "x"},
        12,
    ],
)
def test_filter_clause_rejects_invalid_shapes(value: object) -> None:
    with pytest.raises(ValueError):
        filter_clause(value)  # type: ignore[arg-type]


def test_normalize_filters_enforces_names_count_and_allowlist() -> None:
    assert normalize_filters({"provider": "anthropic"}) == {
        "provider": FilterClause("is", ("anthropic",))
    }
    with pytest.raises(ValueError, match="at most"):
        normalize_filters({f"k{i}": "v" for i in range(MAX_FILTERS + 1)})
    for bad_name in ("", "x" * 81):
        with pytest.raises(ValueError, match="names"):
            normalize_filters({bad_name: "v"})
    with pytest.raises(ValueError, match="unknown filters"):
        normalize_filters({"model": "x"}, allowed=("provider",))


@pytest.mark.parametrize(
    ("clause", "expected"),
    [
        (FilterClause("is", ("ALPHA",)), True),
        (FilterClause("one_of", ("beta", "alpha")), True),
        (FilterClause("is_not", ("beta",)), True),
        (FilterClause("not_one_of", ("beta",)), True),
        (FilterClause("contains", ("LPH",)), True),
        (FilterClause("not_contains", ("zzz",)), True),
        (FilterClause("exists"), True),
        (FilterClause("not_exists"), False),
    ],
)
def test_filter_matches_is_case_insensitive_and_handles_missing(
    clause: FilterClause, expected: bool
) -> None:
    assert filter_matches((None, "", "Alpha"), clause) is expected


def test_exact_and_token_filters_use_safe_defaults() -> None:
    filters = {
        "interval": FilterClause("is", ("week",)),
        "token_type": FilterClause("not_one_of", ("cache",)),
    }
    assert exact_filter(filters, "interval", "day") == "week"
    assert exact_filter(filters, "missing", "day") == "day"
    assert exact_filter({"interval": FilterClause("exists")}, "interval", "day") == "day"
    assert token_type_matches("input", filters)
    assert not token_type_matches("cache", filters)
    assert token_type_matches("cache", {})
