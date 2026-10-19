import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.inventory import run_inventory_sync
from costura.providers.anthropic.sync import run_cost_sync, run_usage_sync
from costura.spend.allocate import run_allocation
from costura.spend.filters import FilterClause, filter_matches
from costura.spend.query import QuerySpec, query_spend
from tests.conftest import ORG_ID, target
from tests.support.spend import AUGUST, FIXTURE_END, FIXTURE_START

QUERY = "/api/v1/orgs/default/query"


@pytest.fixture
def query_synced(db_session: Session, anthropic_client: AnthropicAdminClient) -> None:
    unit = target(db_session, ORG_ID, "anthropic")
    run_cost_sync(db_session, unit, anthropic_client, FIXTURE_START, FIXTURE_END)
    run_usage_sync(db_session, unit, anthropic_client, FIXTURE_START, FIXTURE_END)
    run_inventory_sync(db_session, unit, anthropic_client)
    run_allocation(db_session, ORG_ID, "anthropic", AUGUST)


def test_query_spec_rejects_removed_measures_and_unbounded_queries() -> None:
    base = {
        "dimensions": (),
        "filters": {},
        "start": date(2026, 8, 1),
        "end": date(2026, 8, 31),
        "interval": "day",
        "top": 8,
    }
    assert QuerySpec(measure="billed_usd", **{**base, "top": 200}).top == 200
    with pytest.raises(ValueError, match="measure must be one of"):
        QuerySpec(measure="list_usd", **base)
    with pytest.raises(ValueError, match="measure must be one of"):
        QuerySpec(measure="estimated_usd", **base)
    with pytest.raises(ValueError, match="measure must be one of"):
        QuerySpec(measure="telemetry:requests", **base)
    with pytest.raises(ValueError, match="unknown dimensions"):
        QuerySpec(measure="billed_usd", **{**base, "dimensions": ("tag:team",)})
    with pytest.raises(ValueError, match="at most 3"):
        QuerySpec(
            measure="billed_usd",
            **{**base, "dimensions": ("provider", "workspace", "model", "api_key")},
        )
    with pytest.raises(ValueError, match="366 buckets"):
        QuerySpec(
            measure="billed_usd",
            **{**base, "end": date(2027, 8, 31)},
        )
    with pytest.raises(ValueError, match="top must be between 1 and 200"):
        QuerySpec(measure="billed_usd", **{**base, "top": 201})
    with pytest.raises(ValueError, match="projection must be one of"):
        QuerySpec(measure="billed_usd", **base, projection="quadratic")
    with pytest.raises(ValueError, match="lookback must be between 2 and 90"):
        QuerySpec(measure="billed_usd", **base, projection="linear", lookback=1)
    with pytest.raises(ValueError, match="horizon must be between 1 and 31"):
        QuerySpec(measure="billed_usd", **base, projection="linear", horizon=32)


def test_query_buckets_billed_spend_and_usage_measures(
    db_session: Session, query_synced: None
) -> None:
    billed = query_spend(
        db_session,
        org_id=ORG_ID,
        spec=QuerySpec(
            measure="billed_usd",
            dimensions=("workspace", "model"),
            filters={"provider": "anthropic"},
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
            interval="week",
            top=8,
            compare="previous_period",
        ),
    )

    assert billed.source == "allocated"
    assert len(billed.buckets) == len(billed.total) == 6
    assert sum(billed.total) == Decimal("64.615")
    assert billed.series[0].keys == {
        "workspace": "wrkspc_redacted_a",
        "model": "claude-sonnet-4-6",
    }
    assert billed.comparison is not None
    assert len(billed.comparison.buckets) == len(billed.buckets)
    assert len(billed.comparison.total) == len(billed.total)

    tokens = query_spend(
        db_session,
        org_id=ORG_ID,
        spec=QuerySpec(
            measure="tokens_cache_write",
            dimensions=("api_key",),
            filters={"provider": "anthropic"},
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
            interval="month",
            top=8,
        ),
    )
    assert tokens.source == "usage"
    assert sum(tokens.total) == Decimal("1250")


def test_query_groups_and_filters_by_canonical_model_taxonomy(
    db_session: Session, query_synced: None
) -> None:
    result = query_spend(
        db_session,
        org_id=ORG_ID,
        spec=QuerySpec(
            measure="billed_usd",
            dimensions=("model_brand", "model_family", "model_channel"),
            filters={"provider": "anthropic", "model_lifecycle": "Current"},
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
            interval="month",
            top=8,
        ),
    )

    assert result.series
    assert {row.keys["model_brand"] for row in result.series} == {"Claude"}
    assert {row.keys["model_channel"] for row in result.series} == {"Anthropic API"}
    assert {row.keys["model_family"] for row in result.series} <= {
        "Claude Haiku",
        "Claude Opus",
        "Claude Sonnet",
    }


def test_query_groups_billed_and_usage_by_canonical_token_type(
    db_session: Session, query_synced: None
) -> None:
    base = {
        "dimensions": ("token_type",),
        "filters": {"provider": "anthropic"},
        "start": date(2026, 8, 1),
        "end": date(2026, 8, 31),
        "interval": "month",
        "top": 8,
    }
    billed = query_spend(db_session, org_id=ORG_ID, spec=QuerySpec(measure="billed_usd", **base))
    usage = query_spend(db_session, org_id=ORG_ID, spec=QuerySpec(measure="tokens_total", **base))
    filtered = query_spend(
        db_session,
        org_id=ORG_ID,
        spec=QuerySpec(
            measure="tokens_total",
            **{**base, "filters": {"provider": "anthropic", "token_type": "Cache Read"}},
        ),
    )

    assert {row.keys["token_type"] for row in billed.series} <= {
        "Input",
        "Output",
        "Cache Read",
        "Cache Write",
        "Other",
    }
    assert {"Input", "Output", "Cache Read", "Cache Write"} <= {
        row.keys["token_type"] for row in usage.series
    }
    assert {row.keys["token_type"] for row in filtered.series} == {"Cache Read"}


@pytest.mark.parametrize(
    ("clause", "expected"),
    [
        (FilterClause("is", ("wrkspc_redacted_a",)), Decimal("60.11")),
        (FilterClause("is_not", ("wrkspc_redacted_a",)), Decimal("4.505")),
        (
            FilterClause("one_of", ("wrkspc_redacted_a", "missing")),
            Decimal("60.11"),
        ),
        (FilterClause("not_one_of", ("wrkspc_redacted_a",)), Decimal("4.505")),
        (FilterClause("contains", ("redacted_a",)), Decimal("60.11")),
        (FilterClause("not_contains", ("redacted_a",)), Decimal("4.505")),
        (FilterClause("exists"), Decimal("60.11")),
        (FilterClause("not_exists"), Decimal("4.505")),
    ],
)
def test_query_filter_operators_apply_sql_null_semantics(
    db_session: Session,
    query_synced: None,
    clause: FilterClause,
    expected: Decimal,
) -> None:
    result = query_spend(
        db_session,
        org_id=ORG_ID,
        spec=QuerySpec(
            measure="billed_usd",
            dimensions=(),
            filters={
                "provider": "anthropic",
                "workspace": clause,
            },
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
            interval="month",
            top=8,
        ),
    )

    assert sum(result.total) == expected


@pytest.mark.parametrize(
    ("clause", "expected"),
    [
        (FilterClause("is", ("Claude Sonnet",)), True),
        (FilterClause("is_not", ("Claude Opus",)), True),
        (FilterClause("one_of", ("Claude Opus", "Claude Sonnet")), True),
        (FilterClause("not_one_of", ("Claude Opus",)), True),
        (FilterClause("contains", ("sonnet",)), True),
        (FilterClause("not_contains", ("opus",)), True),
        (FilterClause("exists"), True),
        (FilterClause("not_exists"), False),
    ],
)
def test_filter_operators_apply_python_semantics(clause: FilterClause, expected: bool) -> None:
    assert filter_matches(("Claude Sonnet",), clause) is expected


def test_python_exists_treats_derived_unknown_sentinel_as_absent() -> None:
    candidates = ("__unknown_creator__",)

    assert filter_matches(candidates, FilterClause("is", candidates))
    assert filter_matches(candidates, FilterClause("not_exists"))


def test_queries_route_matches_one_query_per_measure(
    client: TestClient, query_synced: None
) -> None:
    shared = {
        "dimensions": "workspace",
        "provider": "anthropic",
        "start": "2026-08-01",
        "end": "2026-08-31",
        "interval": "day",
        "top": 5,
        "projection": "linear",
        "lookback": 4,
        "horizon": 2,
    }
    response = client.get(
        "/api/v1/orgs/default/queries",
        params={**shared, "measures": "billed_usd,tokens_total"},
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["measure"] for item in body["results"]] == ["billed_usd", "tokens_total"]
    billed = client.get(QUERY, params={**shared, "measure": "billed_usd"}).json()
    tokens = client.get(
        QUERY, params={**shared, "measure": "tokens_total", "projection": "none"}
    ).json()
    assert body["results"][0] == billed
    assert body["results"][1] == tokens
    assert body["results"][0]["projection"]["mode"] == "linear"
    assert body["results"][1]["projection"] is None
    assert body["results"][0]["source"] == "allocated"
    assert body["results"][1]["source"] == "usage"

    empty = client.get("/api/v1/orgs/default/queries", params={**shared, "measures": ""})
    assert empty.status_code == 422
    assert (
        client.get(
            "/api/v1/orgs/default/queries",
            params={**shared, "measures": "billed_usd,billed_usd"},
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/orgs/default/queries", params={**shared, "measures": "list_usd"}
        ).status_code
        == 422
    )


def test_query_route_json_csv_and_bounds(client: TestClient, query_synced: None) -> None:
    params = {
        "measure": "billed_usd",
        "dimensions": "workspace,model",
        "provider": "anthropic",
        "start": "2026-08-01",
        "end": "2026-08-31",
        "interval": "week",
        "top": 1,
        "compare": "previous_year",
        "projection": "linear",
        "lookback": 2,
        "horizon": 3,
    }
    response = client.get(QUERY, params=params)

    assert response.status_code == 200
    body = response.json()
    assert body["dimensions"] == ["workspace", "model"]
    assert body["source"] == "allocated"
    assert len(body["series"]) == 1 and body["other"] is not None
    assert len(body["buckets"]) == len(body["total"]) == 6
    assert len(body["comparison"]["total"]) == len(body["total"])
    assert body["comparison"]["start"] == "2025-08-01"
    assert body["projection"]["mode"] == "linear"
    assert body["projection"]["lookback"] == 2
    assert body["projection"]["horizon"] == 3
    assert body["projection"]["buckets"] == ["2026-09-07", "2026-09-14", "2026-09-21"]
    assert len(body["projection"]["values"]) == 3
    assert body["projection"]["anchor"] == body["total"][-1]

    csv_response = client.get(QUERY, params={**params, "format": "csv"})
    rows = list(csv.reader(io.StringIO(csv_response.text)))
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert (
        "billed_usd-2026-08-01-2026-08-31-week.csv" in csv_response.headers["content-disposition"]
    )
    assert rows[0] == [
        "bucket",
        "series_type",
        "workspace_key",
        "workspace_label",
        "model_key",
        "model_label",
        "provider",
        "value",
    ]
    assert {row[1] for row in rows[1:]} == {
        "series",
        "other",
        "total",
        "comparison_series",
        "comparison_total",
        "projection",
    }
    comparison_rows = [row for row in rows[1:] if row[1] == "comparison_total"]
    assert len(comparison_rows) == len(body["comparison"]["buckets"])
    assert comparison_rows[0][0] == "2025-08-01"
    projection_rows = [row for row in rows[1:] if row[1] == "projection"]
    assert [row[0] for row in projection_rows] == body["projection"]["buckets"]
    assert [row[-1] for row in projection_rows] == body["projection"]["values"]

    assert client.get(QUERY, params={**params, "measure": "estimated_usd"}).status_code == 422
    assert client.get(QUERY, params={**params, "measure": "list_usd"}).status_code == 422
    assert client.get(QUERY, params={**params, "measure": "telemetry:requests"}).status_code == 422
    assert client.get(QUERY, params={**params, "dimensions": "tag:team"}).status_code == 422
    assert client.get(QUERY, params={**params, "top": 200}).status_code == 200
    assert client.get(QUERY, params={**params, "top": 201}).status_code == 422
    assert client.get(QUERY, params={**params, "projection": "quadratic"}).status_code == 422
    assert client.get(QUERY, params={**params, "lookback": 1}).status_code == 422
    assert client.get(QUERY, params={**params, "lookback": 91}).status_code == 422
    assert client.get(QUERY, params={**params, "horizon": 0}).status_code == 422
    assert client.get(QUERY, params={**params, "horizon": 32}).status_code == 422
    assert (
        client.get(
            QUERY, params={**params, "dimensions": "provider,workspace,model,api_key"}
        ).status_code
        == 422
    )
    assert (
        client.get(QUERY, params={**params, "start": "2026-09-01", "end": "2026-08-01"}).status_code
        == 422
    )


@pytest.mark.parametrize(
    ("interval", "start", "end", "expected"),
    [
        ("day", "2026-08-30", "2026-08-31", ["2026-09-01", "2026-09-02"]),
        ("week", "2026-08-24", "2026-08-31", ["2026-09-07", "2026-09-14"]),
        ("month", "2026-07-01", "2026-08-31", ["2026-09-01", "2026-10-01"]),
    ],
)
def test_query_projection_dates_follow_interval_boundaries(
    client: TestClient,
    query_synced: None,
    interval: str,
    start: str,
    end: str,
    expected: list[str],
) -> None:
    response = client.get(
        QUERY,
        params={
            "measure": "billed_usd",
            "start": start,
            "end": end,
            "interval": interval,
            "projection": "linear",
            "lookback": 2,
            "horizon": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["projection"]["buckets"] == expected


def test_query_route_accepts_repeatable_filter_clauses(
    client: TestClient, query_synced: None
) -> None:
    params = [
        ("measure", "billed_usd"),
        ("dimensions", "workspace"),
        ("start", "2026-08-01"),
        ("end", "2026-08-31"),
        ("interval", "month"),
        ("f", "provider:is:anthropic"),
        ("f", "workspace:not_exists:"),
    ]
    response = client.get(QUERY, params=params)

    assert response.status_code == 200
    assert response.json()["total"] == ["4.51"]
    assert (
        client.get(QUERY, params={**dict(params), "f": "workspace:unknown:value"}).status_code
        == 422
    )
    duplicate = [*params, ("f", "workspace:is:wrkspc_redacted_a")]
    assert client.get(QUERY, params=duplicate).status_code == 422


def test_query_route_serializes_counters_as_integers(
    client: TestClient, query_synced: None
) -> None:
    body = client.get(
        QUERY,
        params={
            "measure": "tokens_total",
            "dimensions": "model",
            "start": "2026-08-01",
            "end": "2026-08-31",
            "interval": "month",
            "provider": "anthropic",
        },
    ).json()

    assert isinstance(body["total"][0], int)
    assert sum(body["total"]) > 0


def _steady(day: date) -> list[tuple[str | None, str, str, Decimal]]:
    return [("wrkspc_a", "claude-sonnet-4", "apikey_steady", Decimal("10.00"))]


def _compared(db_session: Session, start: date, end: date, today: date) -> tuple:
    result = query_spend(
        db_session,
        org_id=ORG_ID,
        spec=QuerySpec(
            measure="billed_usd",
            dimensions=(),
            filters={},
            start=start,
            end=end,
            interval="day",
            top=8,
            compare="previous_period",
        ),
        today=today,
    )
    assert result.comparison is not None
    comparison = result.comparison
    return comparison.start, comparison.end, sum(comparison.total)


def test_previous_period_of_a_month_is_the_previous_calendar_month(db_session: Session) -> None:
    from tests.seed import seed_days

    seed_days(db_session, ORG_ID, "anthropic", date(2026, 8, 1), date(2026, 10, 1), _steady)

    september = _compared(db_session, date(2026, 9, 1), date(2026, 9, 30), date(2026, 10, 14))
    assert september == (date(2026, 8, 1), date(2026, 8, 31), Decimal("310.00"))

    days = _compared(db_session, date(2026, 9, 5), date(2026, 9, 14), date(2026, 10, 14))
    assert days == (date(2026, 8, 26), date(2026, 9, 4), Decimal("100.00"))


def test_previous_period_of_a_month_in_progress_is_the_same_days(db_session: Session) -> None:
    from tests.seed import seed_days

    seed_days(db_session, ORG_ID, "anthropic", date(2026, 8, 1), date(2026, 9, 15), _steady)

    compared = _compared(db_session, date(2026, 9, 1), date(2026, 9, 30), date(2026, 9, 15))
    assert compared == (date(2026, 8, 1), date(2026, 8, 14), Decimal("140.00"))
