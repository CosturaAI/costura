import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura import credit_prices
from costura.models import (
    ProviderReportPage,
    ProviderUser,
    SpendAllocatedLine,
    SpendCostLine,
    SpendUsageLine,
)
from costura.providers.codex.client import FetchedPage
from costura.providers.codex.normalize import (
    _actor,
    _amount,
    _client,
    _count,
    _epoch,
    _usage_buckets,
    aggregate_user_lines,
    cost_lines_from_payload,
    page_credits,
    user_lines_from_payload,
)
from costura.providers.codex.pricing import effective_price
from costura.providers.codex.sync import run_cost_sync, run_user_sync
from costura.providers.lines import NormalizeError, UsageLine
from costura.providers.normalization import text_or
from costura.providers.records import USER_KIND_SERVICE_ACCOUNT, UserRecord
from costura.spend.allocate import run_allocation
from costura.spend.reconcile import reconcile
from costura.spend.window import Window
from tests.conftest import ORG_ID, target
from tests.support.runs import cost_total, usage_total

FIXTURE = Path(__file__).parent / "fixtures" / "codex" / "official_usage_page.json"
WORKSPACE_ID = "11111111-2222-4333-8444-555555555555"
START = datetime(2026, 9, 18, tzinfo=UTC)
END = datetime(2026, 9, 19, tzinfo=UTC)


def payload() -> dict:
    return json.loads(FIXTURE.read_text())


class CodexFixtureClient:
    def usage_pages(
        self,
        _start: datetime,
        _end: datetime,
        *,
        workspace: bool = False,
        limit: int = 1000,
    ):
        data = payload()
        if workspace:
            data["data"][0]["actor"] = None
            data["data"][0]["user_id"] = None
        yield FetchedPage(
            page_index=0,
            request_params={
                "start_time": int(START.timestamp()),
                "end_time": int(END.timestamp()),
                "group_by": "day",
                "limit": limit,
                **({"group": "workspace"} if workspace else {}),
            },
            payload=data,
        )


def test_official_usage_shape_prices_credits_and_tracks_user_tokens() -> None:
    data = payload()
    price = credit_prices.CreditPrice(
        effective_from=date(2026, 9, 18),
        price_per_credit=Decimal("0.08"),
    )

    costs = cost_lines_from_payload(data, workspace_id=WORKSPACE_ID, prices=[price])
    user_rows = user_lines_from_payload(data, workspace_id=WORKSPACE_ID, prices=[price])
    usage = [row for row in user_rows if hasattr(row, "uncached_input_tokens")]

    assert [(line.model, line.service_tier, line.raw_amount_minor) for line in costs] == [
        ("gpt-5.4", "standard", "10"),
        ("gpt-5.5", "fast", "2.5"),
    ]
    assert sum((line.amount for line in costs), Decimal("0")) == Decimal("1.000")
    assert sum(line.uncached_input_tokens for line in usage) == 1000
    assert sum(line.cache_read_tokens for line in usage) == 250
    assert sum(line.output_tokens for line in usage) == 400
    assert sum(line.request_count for line in usage) == 30
    assert sum((line.amount or Decimal("0") for line in usage), Decimal("0")) == Decimal("1.000")
    assert page_credits(data, START, END) == Decimal("12.5")


def test_missing_price_writes_no_fake_cost_and_is_reported() -> None:
    data = payload()

    assert cost_lines_from_payload(data, workspace_id=WORKSPACE_ID, prices=[]) == []
    usage = user_lines_from_payload(data, workspace_id=WORKSPACE_ID, prices=[])
    assert all(row.amount is None for row in usage if hasattr(row, "amount"))


def test_codex_scalar_normalizers_reject_ambiguous_values() -> None:
    assert _count(None, field="count") == 0
    assert _amount(None, field="amount") == 0
    assert text_or(None, field="text", default="fallback") == "fallback"
    for value in (True, "1", -1):
        with pytest.raises(NormalizeError):
            _count(value, field="count")
    for value in (True, object(), "-1", "NaN", "Infinity"):
        with pytest.raises(NormalizeError):
            _amount(value, field="amount")
    for value in (True, "1", 10**30):
        with pytest.raises(NormalizeError):
            _epoch(value, field="time")
    with pytest.raises(NormalizeError):
        text_or(1, field="text")


def test_codex_bucket_client_and_actor_fallbacks() -> None:
    assert _usage_buckets({"totals": {"credits": 2}}) == [
        {"model": "(none)", "speed": "standard", "credits": 2}
    ]
    with pytest.raises(NormalizeError, match="totals"):
        _usage_buckets({})
    assert _client({"clients": [{"client_id": "CLI"}, {"client_id": "CLI"}]}) == "CLI"
    assert _client({"clients": [{"client_id": "CLI"}, {"client_id": "IDE"}]}) == "Codex"
    with pytest.raises(NormalizeError, match="clients"):
        _client({})

    user_id, record = _actor({"actor": {"user_id": "svc", "type": "SERVICE_ACCOUNT", "email": ""}})
    assert user_id == "svc"
    assert record.kind == USER_KIND_SERVICE_ACCOUNT
    assert record.email == "svc"
    with pytest.raises(NormalizeError, match="no actor"):
        _actor({})


def test_codex_aggregation_keeps_one_user_record() -> None:
    row = payload()["data"][0]
    price = credit_prices.CreditPrice(
        effective_from=date(2026, 9, 18), price_per_credit=Decimal("0.08")
    )
    lines = user_lines_from_payload({"data": [row, row]}, workspace_id=WORKSPACE_ID, prices=[price])
    aggregated = aggregate_user_lines(lines)
    assert sum(isinstance(line, UserRecord) for line in aggregated) == 1
    assert sum(isinstance(line, UsageLine) for line in aggregated) == 2


def test_codex_pages_ignore_non_rows_and_window_outside_rows() -> None:
    data = payload()
    data["data"].insert(0, "not-a-row")
    assert page_credits(data, END, END + (END - START)) == 0


def test_credit_schedule_boundaries_validation_and_effective_price(
    db_session: Session,
) -> None:
    unit = target(db_session, ORG_ID, "codex")
    account = credit_prices.codex_account(db_session, ORG_ID, unit.account_id)
    account.external_id = WORKSPACE_ID
    first = credit_prices.create_price(
        db_session,
        ORG_ID,
        unit.account_id,
        effective_from=date(2026, 8, 18),
        price_per_credit=Decimal("0.08"),
        created_by=None,
        today=date(2026, 9, 18),
    )
    second = credit_prices.create_price(
        db_session,
        ORG_ID,
        unit.account_id,
        effective_from=date(2026, 9, 18),
        price_per_credit=Decimal("0.10"),
        created_by=None,
        today=date(2026, 9, 18),
    )

    assert effective_price([first, second], date(2026, 9, 17)) == Decimal("0.08")
    assert effective_price([first, second], date(2026, 9, 18)) == Decimal("0.10")


def test_sync_is_idempotent_allocates_and_reconciles_credits(db_session: Session) -> None:
    unit = target(db_session, ORG_ID, "codex")
    account = credit_prices.codex_account(db_session, ORG_ID, unit.account_id)
    account.external_id = WORKSPACE_ID
    credit_prices.create_price(
        db_session,
        ORG_ID,
        unit.account_id,
        effective_from=date(2026, 9, 18),
        price_per_credit=Decimal("0.08"),
        created_by=None,
        today=date(2026, 9, 18),
    )
    client = CodexFixtureClient()
    cost = run_cost_sync(db_session, unit, client, START, END)
    users = run_user_sync(db_session, unit, client, START, END)

    assert cost_total(db_session, cost.run_id) == Decimal("1.000")
    assert usage_total(db_session, users.run_id, "amount") == Decimal("1.000")
    assert db_session.scalar(select(func.count()).select_from(SpendCostLine)) == 2
    assert db_session.scalar(select(func.count()).select_from(SpendUsageLine)) == 2
    assert db_session.scalar(select(func.count()).select_from(ProviderUser)) == 1
    assert db_session.scalar(select(func.count()).select_from(ProviderReportPage)) == 2

    again = run_cost_sync(db_session, unit, client, START, END)
    run_user_sync(db_session, unit, client, START, END)
    assert again.run_id != cost.run_id
    assert db_session.scalar(select(func.count()).select_from(SpendCostLine)) == 2
    assert db_session.scalar(select(func.count()).select_from(SpendUsageLine)) == 2

    allocation = run_allocation(
        db_session,
        ORG_ID,
        "codex",
        Window(START, END),
        account_id=unit.account_id,
    )
    assert allocation.balanced is True
    assert db_session.scalar(select(func.sum(SpendAllocatedLine.amount))) == Decimal("1.000")

    report = reconcile(
        db_session,
        org_id=ORG_ID,
        provider="codex",
        window=Window(START, END),
        reported_total=Decimal("1"),
        account_id=unit.account_id,
    )
    assert report.codex_credit_check is not None
    assert report.codex_credit_check.ok is True
    assert report.codex_credit_check.workspace_credits == Decimal("12.5")
    assert report.codex_credit_check.user_credits == Decimal("12.5")


def test_sync_missing_price_fails_credit_reconciliation_visibly(
    db_session: Session,
) -> None:
    unit = target(db_session, ORG_ID, "codex")
    account = credit_prices.codex_account(db_session, ORG_ID, unit.account_id)
    account.external_id = WORKSPACE_ID
    client = CodexFixtureClient()
    run_cost_sync(db_session, unit, client, START, END)
    run_user_sync(db_session, unit, client, START, END)

    assert db_session.scalar(select(func.count()).select_from(SpendCostLine)) == 0
    report = reconcile(
        db_session,
        org_id=ORG_ID,
        provider="codex",
        window=Window(START, END),
        reported_total=Decimal("0"),
        account_id=unit.account_id,
    )
    assert report.codex_credit_check is not None
    assert report.codex_credit_check.ok is False
    assert report.codex_credit_check.missing_price_days == ["2026-09-18"]
