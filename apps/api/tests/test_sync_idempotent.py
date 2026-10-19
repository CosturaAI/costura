from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import ProviderReportPage, ProviderSyncRun, SpendCostLine, SpendUsageLine
from costura.providers.anthropic.client import AnthropicAdminClient, AnthropicApiError
from costura.providers.anthropic.sync import (
    ENDPOINT_COST,
    ENDPOINT_COST_TOTAL,
    ENDPOINT_USAGE,
    run_cost_sync,
    run_cost_total_sync,
    run_usage_sync,
)
from tests.conftest import ORG_ID, target
from tests.support.runs import cost_total
from tests.test_anthropic_normalize import (
    COST_FIXTURE_DISTINCT_KEYS,
    COST_FIXTURE_RESULTS,
    COST_FIXTURE_TOTAL,
    USAGE_FIXTURE_TOTALS,
)

START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 8, 5, tzinfo=UTC)


def _cost_state(session: Session) -> tuple[int, Decimal]:
    count, total = session.execute(
        select(func.count(), func.coalesce(func.sum(SpendCostLine.amount), 0))
    ).one()
    return count, Decimal(total)


def _usage_state(session: Session) -> tuple[int, dict[str, int]]:
    count = session.scalar(select(func.count()).select_from(SpendUsageLine))
    totals = {
        name: int(session.scalar(select(func.sum(getattr(SpendUsageLine, name)))) or 0)
        for name in USAGE_FIXTURE_TOTALS
    }
    return count or 0, totals


def test_cost_sync_stores_pages_and_upserts_lines(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    summary = run_cost_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), anthropic_client, START, END
    )

    assert summary.endpoint == ENDPOINT_COST
    assert summary.pages_fetched == 2
    assert summary.raw_results == COST_FIXTURE_RESULTS
    assert summary.rows_upserted == COST_FIXTURE_DISTINCT_KEYS
    assert cost_total(db_session, summary.run_id) == COST_FIXTURE_TOTAL

    run = db_session.get(ProviderSyncRun, summary.run_id)
    assert run is not None
    assert run.status == "succeeded"
    assert run.finished_at is not None
    assert (run.pages_fetched, run.raw_results, run.rows_upserted) == (2, 7, 6)

    pages = db_session.scalars(
        select(ProviderReportPage).order_by(ProviderReportPage.page_index)
    ).all()
    assert [p.page_index for p in pages] == [0, 1]
    assert pages[1].request_params["page"] == "page_cost_2"
    assert pages[0].payload["data"][0]["results"][0]["amount"] == "123.78912"

    assert _cost_state(db_session) == (COST_FIXTURE_DISTINCT_KEYS, COST_FIXTURE_TOTAL)
    default_workspace = db_session.scalars(
        select(SpendCostLine).where(SpendCostLine.workspace_id.is_(None))
    ).all()
    assert len(default_workspace) == 3


def test_cost_sync_twice_is_idempotent(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    first = run_cost_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), anthropic_client, START, END
    )
    state_after_first = _cost_state(db_session)
    first_seen = {
        line.id: (line.first_seen_at, line.last_seen_at, line.sync_run_id)
        for line in db_session.scalars(select(SpendCostLine)).all()
    }
    db_session.expire_all()

    second = run_cost_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), anthropic_client, START, END
    )

    assert _cost_state(db_session) == state_after_first
    assert second.rows_upserted == first.rows_upserted
    assert db_session.scalar(select(func.count()).select_from(ProviderReportPage)) == 4
    runs = db_session.scalars(select(ProviderSyncRun).order_by(ProviderSyncRun.id)).all()
    assert [r.status for r in runs] == ["succeeded", "succeeded"]
    for line in db_session.scalars(select(SpendCostLine)).all():
        original_first_seen, original_last_seen, original_run = first_seen[line.id]
        assert line.first_seen_at == original_first_seen
        assert line.last_seen_at >= original_last_seen
        assert line.sync_run_id == second.run_id != original_run


def test_usage_sync_and_idempotency(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    summary = run_usage_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), anthropic_client, START, END
    )

    assert summary.endpoint == ENDPOINT_USAGE
    assert summary.pages_fetched == 12  # 2 fixture pages x 6 (context_window, inference_geo) slices
    assert summary.raw_results == 4
    assert summary.rows_upserted == 4
    assert _usage_state(db_session) == (4, USAGE_FIXTURE_TOTALS)

    run_usage_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), anthropic_client, START, END
    )

    assert _usage_state(db_session) == (4, USAGE_FIXTURE_TOTALS)
    no_key = db_session.scalars(
        select(SpendUsageLine).where(SpendUsageLine.api_key_id.is_(None))
    ).all()
    assert sorted(line.account_id or "" for line in no_key) == ["", "user_redacted_alice"]
    long_context = db_session.scalars(
        select(SpendUsageLine).where(SpendUsageLine.context_window == "200k-1M")
    ).all()
    assert sorted(line.inference_geo or "" for line in long_context) == ["us", "us"]


def test_failed_fetch_marks_run_failed_and_keeps_pages(db_session: Session) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            from tests.conftest import load_fixture

            return httpx.Response(200, json=load_fixture("cost_report_page1.json"))
        return httpx.Response(500, json={"error": "boom"})

    client = AnthropicAdminClient(
        admin_key="k", transport=httpx.MockTransport(handler), max_retries=0, sleep=lambda _: None
    )
    with client, pytest.raises(AnthropicApiError):
        run_cost_sync(db_session, target(db_session, ORG_ID, "anthropic"), client, START, END)

    run = db_session.scalars(select(ProviderSyncRun)).one()
    assert run.status == "failed"
    assert run.error is not None and "500" in run.error
    assert run.pages_fetched == 1
    assert db_session.scalar(select(func.count()).select_from(ProviderReportPage)) == 1
    assert _cost_state(db_session) == (0, Decimal("0"))


def test_cost_total_sync_keeps_pages_and_writes_no_lines(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    run_cost_sync(db_session, target(db_session, ORG_ID, "anthropic"), anthropic_client, START, END)
    before = _cost_state(db_session)

    summary = run_cost_total_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), anthropic_client, START, END
    )

    assert summary.endpoint == ENDPOINT_COST_TOTAL
    assert summary.pages_fetched == 1
    assert summary.raw_results == 4
    assert summary.rows_upserted == 0
    assert _cost_state(db_session) == before

    run = db_session.get(ProviderSyncRun, summary.run_id)
    assert run is not None and run.status == "succeeded" and run.rows_upserted == 0
    pages = db_session.scalars(
        select(ProviderReportPage).where(ProviderReportPage.sync_run_id == summary.run_id)
    ).all()
    assert len(pages) == 1
    assert pages[0].endpoint == ENDPOINT_COST_TOTAL
    assert "group_by[]" not in pages[0].request_params


def test_a_line_the_provider_stops_reporting_leaves_the_ledger(db_session: Session) -> None:
    from tests.conftest import load_fixture

    full = load_fixture("cost_report_page1.json")
    full["has_more"], full["next_page"] = False, None
    restated = {**full, "data": [{**full["data"][0], "results": full["data"][0]["results"][1:]}]}
    payloads = [full, restated]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payloads[0])

    client = AnthropicAdminClient(
        admin_key="k", transport=httpx.MockTransport(handler), max_retries=0, sleep=lambda _: None
    )
    unit = target(db_session, ORG_ID, "anthropic")
    with client:
        run_cost_sync(db_session, unit, client, START, END)
        payloads.pop(0)
        run_cost_sync(db_session, unit, client, START, END)

    cents = sum(Decimal(result["amount"]) for result in restated["data"][0]["results"])
    expected = cents / 100
    assert _cost_state(db_session)[1] == expected
