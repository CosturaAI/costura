from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import ProviderSyncRun, SpendAllocatedLine, SpendCostLine, SpendUsageLine
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.sync import run_cost_sync, run_usage_sync
from costura.spend.allocate import run_allocation
from costura.spend.allocation_check import allocation_check
from costura.spend.allocation_split import REASON_NO_USAGE, REASON_UNSUPPORTED_COST_TYPE
from costura.spend.window import Window
from tests.conftest import ORG_ID, account_of, target
from tests.support.spend import AUGUST, FIXTURE_END, FIXTURE_START

DAY = datetime(2026, 8, 10, tzinfo=UTC)
WS = "wrkspc_redacted_a"


def _run(db_session: Session, endpoint: str) -> int:
    run = ProviderSyncRun(
        organization_id=ORG_ID,
        provider="anthropic",
        provider_account_id=account_of(db_session, ORG_ID, "anthropic"),
        endpoint=endpoint,
        window_start=AUGUST.start,
        window_end=AUGUST.end,
        status="succeeded",
    )
    db_session.add(run)
    db_session.flush()
    return run.id


def _cost(
    db_session: Session,
    run_id: int,
    amount: str,
    *,
    day: datetime = DAY,
    workspace_id: str | None = WS,
    cost_type: str = "tokens",
    model: str | None = "claude-opus-5",
    token_type: str | None = "uncached_input_tokens",
    context_window: str | None = "0-200k",
    description: str = "x",
) -> None:
    db_session.add(
        SpendCostLine(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=account_of(db_session, ORG_ID, "anthropic"),
            period_start=day,
            period_end=day + timedelta(days=1),
            workspace_id=workspace_id,
            description=description,
            cost_type=cost_type,
            model=model,
            token_type=token_type,
            service_tier="standard" if cost_type == "tokens" else None,
            context_window=context_window if cost_type == "tokens" else None,
            inference_geo="global" if cost_type == "tokens" else None,
            amount=Decimal(amount),
            currency="USD",
            raw_amount_minor=amount,
            sync_run_id=run_id,
        )
    )


def _usage(
    db_session: Session,
    run_id: int,
    *,
    api_key_id: str | None,
    account_id: str | None = None,
    day: datetime = DAY,
    workspace_id: str | None = WS,
    model: str = "claude-opus-5",
    context_window: str | None = "0-200k",
    uncached: int = 0,
    cache_read: int = 0,
    output: int = 0,
    web_search: int = 0,
) -> None:
    db_session.add(
        SpendUsageLine(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=account_of(db_session, ORG_ID, "anthropic"),
            period_start=day,
            period_end=day + timedelta(days=1),
            api_key_id=api_key_id,
            account_id=account_id,
            workspace_id=workspace_id,
            model=model,
            service_tier="standard",
            context_window=context_window,
            inference_geo="global",
            uncached_input_tokens=uncached,
            cache_creation_5m_tokens=0,
            cache_creation_1h_tokens=0,
            cache_read_tokens=cache_read,
            output_tokens=output,
            web_search_requests=web_search,
            sync_run_id=run_id,
        )
    )


def _allocated(db_session: Session) -> list[SpendAllocatedLine]:
    return db_session.scalars(
        select(SpendAllocatedLine).order_by(
            SpendAllocatedLine.period_start,
            SpendAllocatedLine.token_type,
            SpendAllocatedLine.api_key_id,
        )
    ).all()


def test_token_share_splits_each_bucket_exactly(db_session: Session) -> None:
    cost_run = _run(db_session, "cost_report")
    usage_run = _run(db_session, "usage_report_messages")
    _cost(db_session, cost_run, "0.01")
    _cost(db_session, cost_run, "0.01", description="y")  # same bucket, summed to 0.02
    _cost(db_session, cost_run, "9.00", token_type="output_tokens")
    _cost(db_session, cost_run, "100.00", context_window="200k-1M")
    _usage(db_session, usage_run, api_key_id="k1", uncached=1, output=2)
    _usage(db_session, usage_run, api_key_id="k2", uncached=1, output=1)
    _usage(db_session, usage_run, api_key_id="k3", uncached=1)
    _usage(db_session, usage_run, api_key_id="k1", uncached=999, context_window="200k-1M")
    _usage(
        db_session,
        usage_run,
        api_key_id=None,
        account_id="user_a",
        context_window="200k-1M",
        uncached=1,
    )
    db_session.commit()

    summary = run_allocation(db_session, ORG_ID, "anthropic", AUGUST)

    assert summary.currency == "USD"
    assert summary.buckets == 3
    assert summary.cost_total == Decimal("109.02")
    assert summary.allocated_total == Decimal("109.02")
    assert summary.unallocated_total == Decimal("0")
    assert summary.balanced
    assert summary.allocated_rows == 7
    assert summary.unpriced_tokens == {}

    rows = _allocated(db_session)
    by_key = {(r.token_type, r.context_window, r.api_key_id, r.account_id): r for r in rows}
    three_way = [
        by_key[("uncached_input_tokens", "0-200k", k, None)].amount for k in ("k1", "k2", "k3")
    ]
    assert sum(three_way) == Decimal("0.02")
    assert sorted(three_way) == [
        Decimal("0.00666666"),
        Decimal("0.00666667"),
        Decimal("0.00666667"),
    ]
    assert by_key[("output_tokens", "0-200k", "k1", None)].amount == Decimal("6")
    assert by_key[("output_tokens", "0-200k", "k2", None)].amount == Decimal("3")
    long_key = by_key[("uncached_input_tokens", "200k-1M", "k1", None)]
    assert long_key.amount == Decimal("99.9")
    assert (long_key.tokens, long_key.bucket_tokens, long_key.bucket_amount) == (
        999,
        1000,
        Decimal("100"),
    )
    oauth = by_key[("uncached_input_tokens", "200k-1M", None, "user_a")]
    assert oauth.amount == Decimal("0.1")
    assert all(r.unallocated_reason is None for r in rows)
    assert {r.method for r in rows} == {"token_share"}


def test_web_search_and_unallocated_reasons(db_session: Session) -> None:
    cost_run = _run(db_session, "cost_report")
    usage_run = _run(db_session, "usage_report_messages")
    _cost(db_session, cost_run, "1.00", cost_type="web_search", model=None, token_type=None)
    _cost(db_session, cost_run, "2.50", token_type="cache_read_input_tokens")
    _cost(db_session, cost_run, "0.40", cost_type="code_execution", model=None, token_type=None)
    _usage(db_session, usage_run, api_key_id="k1", web_search=3, model="claude-sonnet-5")
    _usage(db_session, usage_run, api_key_id="k2", web_search=1, uncached=500)
    db_session.commit()

    summary = run_allocation(db_session, ORG_ID, "anthropic", AUGUST)

    assert summary.cost_total == Decimal("3.90")
    assert summary.allocated_total == Decimal("1.00")
    assert summary.unallocated_total == Decimal("2.90")
    assert summary.unallocated_by_reason == {
        REASON_NO_USAGE: Decimal("2.50"),
        REASON_UNSUPPORTED_COST_TYPE: Decimal("0.40"),
    }
    assert summary.balanced
    assert summary.unpriced_tokens == {("claude-opus-5", "uncached_input_tokens", "0-200k"): 500}

    rows = _allocated(db_session)
    web = {r.api_key_id: r.amount for r in rows if r.cost_type == "web_search"}
    assert web == {"k1": Decimal("0.75"), "k2": Decimal("0.25")}
    unallocated = {r.unallocated_reason: r for r in rows if r.unallocated_reason}
    assert unallocated[REASON_NO_USAGE].amount == Decimal("2.50")
    assert unallocated[REASON_NO_USAGE].api_key_id is None
    assert unallocated[REASON_NO_USAGE].tokens == 0
    assert unallocated[REASON_UNSUPPORTED_COST_TYPE].cost_type == "code_execution"


def test_second_run_replaces_rows(db_session: Session) -> None:
    cost_run = _run(db_session, "cost_report")
    usage_run = _run(db_session, "usage_report_messages")
    _cost(db_session, cost_run, "10")
    _usage(db_session, usage_run, api_key_id="k1", uncached=1)
    db_session.commit()

    first = run_allocation(db_session, ORG_ID, "anthropic", AUGUST)
    second = run_allocation(db_session, ORG_ID, "anthropic", AUGUST)

    assert first.run_id != second.run_id
    assert db_session.scalar(select(func.count()).select_from(SpendAllocatedLine)) == 1
    assert _allocated(db_session)[0].allocation_run_id == second.run_id
    assert allocation_check(db_session, ORG_ID, "anthropic", AUGUST).run_id == second.run_id
    assert allocation_check(db_session, ORG_ID, "anthropic", Window.for_month("2026-09")) is None
    runs = db_session.scalars(
        select(ProviderSyncRun).where(ProviderSyncRun.endpoint == "allocation")
    ).all()
    assert [(r.status, r.raw_results, r.rows_upserted) for r in runs] == [
        ("succeeded", 1, 1),
        ("succeeded", 1, 1),
    ]


def test_allocation_on_fixtures_balances(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )
    run_usage_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )

    summary = run_allocation(db_session, ORG_ID, "anthropic", AUGUST)

    assert summary.cost_total == Decimal("64.615")
    assert summary.balanced
    # 08-01 default workspace input and output split key1 : playground; 08-03 sonnet cache read
    # goes entirely to alice's OAuth account.
    assert summary.allocated_total == Decimal("1.2378912") + Decimal("2.505") + Decimal("50")
    assert summary.unallocated_by_reason == {
        REASON_NO_USAGE: Decimal("10") + Decimal("0.7621088") + Decimal("0.11")
    }
    rows = _allocated(db_session)
    alice = [r for r in rows if r.account_id == "user_redacted_alice"]
    assert len(alice) == 1 and alice[0].amount == Decimal("50")
    key1 = sum(r.amount for r in rows if r.api_key_id == "apikey_redacted_1")
    playground = sum(
        r.amount
        for r in rows
        if r.api_key_id is None and r.account_id is None and r.unallocated_reason is None
    )
    assert key1 + playground == Decimal("1.2378912") + Decimal("2.505")
    assert (
        summary.unpriced_tokens[("claude-sonnet-4-6", "uncached_input_tokens", "200k-1M")] == 20000
    )
