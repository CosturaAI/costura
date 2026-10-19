"""What a provider reports about its own spend, outside the cost lines: the report pages of the
latest run, the Cursor spend endpoint and seats, and Codex credits priced per account."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import (
    ProviderReportPage,
    ProviderSyncRun,
    SpendCostLine,
)
from costura.providers.codex.normalize import page_credits as codex_page_credits
from costura.providers.codex.sync import ENDPOINT_COST as CODEX_COST_ENDPOINT
from costura.providers.codex.sync import ENDPOINT_USER as CODEX_USER_ENDPOINT
from costura.providers.codex.sync import PRICE_PARAMS_KEY as CODEX_PRICE_PARAMS_KEY
from costura.providers.registry import find_spec, get_spec
from costura.spend.ledger import (
    cost_where,
    has_cost_lines,
    scope_units,
)
from costura.spend.money import STORAGE_EXPONENT
from costura.spend.window import Window


@dataclass(frozen=True)
class CodexCreditCheck:
    workspace_credits: Decimal
    user_credits: Decimal
    missing_price_days: list[str]
    workspace_run_id: int
    user_run_id: int | None

    @property
    def delta(self) -> Decimal:
        return self.workspace_credits - self.user_credits

    @property
    def ok(self) -> bool:
        return (
            self.user_run_id is not None
            and abs(self.delta) <= STORAGE_EXPONENT
            and not self.missing_price_days
        )


def raw_total_of_latest_run(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    account_id: int | None = None,
) -> tuple[int | None, Decimal | None]:
    """Sum the amounts of every raw grouped-cost page in the most recent succeeded run whose
    window covers this one, per account. Returns (run_id, total) or (None, None) when no run
    exists. Over several accounts or providers: the sum, or (None, None) when any account with
    cost lines has no run."""
    return _sum_over_scope(
        session,
        org_id,
        provider,
        window,
        account_id,
        lambda p, a: _page_total_of_latest_run(
            session, org_id, p, a, window, get_spec(p).cost_endpoint
        ),
    )


def provider_total_of_latest_run(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    account_id: int | None = None,
) -> tuple[int | None, Decimal | None]:
    """Sum of the ungrouped control-total run: the organization's own daily totals as the
    provider console shows them (Anthropic `cost_total`, OpenRouter `analytics_total`)."""
    now = datetime.now(UTC)
    spec = find_spec(provider)
    current_live_cycle = (
        spec is not None and spec.live_cycle_total and window.start <= now < window.end
    )
    return _sum_over_scope(
        session,
        org_id,
        provider,
        window,
        account_id,
        lambda p, a: (
            _live_total_of_latest_run(session, org_id, p, a, window)
            if current_live_cycle
            else _page_total_of_latest_run(
                session, org_id, p, a, window, get_spec(p).total_endpoint
            )
        ),
    )


def _live_total_of_latest_run(
    session: Session, org_id: int, provider: str, account_id: int, window: Window
) -> tuple[int | None, Decimal | None]:
    run_id = session.scalar(
        select(ProviderSyncRun.id)
        .where(
            ProviderSyncRun.organization_id == org_id,
            ProviderSyncRun.provider == provider,
            ProviderSyncRun.provider_account_id == account_id,
            ProviderSyncRun.endpoint == get_spec(provider).total_endpoint,
            ProviderSyncRun.status == "succeeded",
            ProviderSyncRun.window_start == window.start,
        )
        .order_by(ProviderSyncRun.id.desc())
        .limit(1)
    )
    if run_id is None:
        return None, None
    total = Decimal("0")
    callback = get_spec(provider).page_amount_with_params
    assert callback is not None
    for payload, params in session.execute(
        select(ProviderReportPage.payload, ProviderReportPage.request_params).where(
            ProviderReportPage.sync_run_id == run_id
        )
    ):
        total += callback(payload, params, window.start, window.end)
    return run_id, total


def _sum_over_scope(
    session: Session,
    org_id: int,
    scope: str,
    window: Window,
    account_id: int | None,
    one: Callable[[str, int], tuple[int | None, Decimal | None]],
) -> tuple[int | None, Decimal | None]:
    """Combine per-account (run_id, total) pairs: the highest run id and the summed total.
    Accounts without any cost line in the window are ignored; an account with cost lines but
    no covering run makes the whole result unknown, so the aggregated figure is never compared
    against a partial sum."""
    run_id: int | None = None
    total = Decimal("0")
    units = scope_units(session, org_id, scope, account_id)
    for name, unit_account in units:
        if len(units) > 1 and not has_cost_lines(session, org_id, name, window, unit_account):
            continue
        one_run, one_total = one(name, unit_account)
        if one_run is None or one_total is None:
            return None, None
        run_id = one_run if run_id is None else max(run_id, one_run)
        total += one_total
    return run_id, (total if run_id is not None else None)


def _page_total_of_latest_run(
    session: Session, org_id: int, provider: str, account_id: int, window: Window, endpoint: str
) -> tuple[int | None, Decimal | None]:
    run_id = session.scalar(
        select(ProviderSyncRun.id)
        .where(
            ProviderSyncRun.organization_id == org_id,
            ProviderSyncRun.provider == provider,
            ProviderSyncRun.provider_account_id == account_id,
            ProviderSyncRun.endpoint == endpoint,
            ProviderSyncRun.status == "succeeded",
            ProviderSyncRun.window_start <= window.start,
            ProviderSyncRun.window_end >= window.end,
        )
        .order_by(ProviderSyncRun.id.desc())
        .limit(1)
    )
    if run_id is None:
        return None, None
    spec = get_spec(provider)
    page_amount = spec.page_amount
    total = Decimal("0")
    for payload, params in session.execute(
        select(ProviderReportPage.payload, ProviderReportPage.request_params).where(
            ProviderReportPage.sync_run_id == run_id
        )
    ):
        if spec.page_amount_with_params is not None:
            total += spec.page_amount_with_params(payload, params, window.start, window.end)
        else:
            total += page_amount(payload, window.start, window.end)
    return run_id, total


def _credit_run(
    session: Session,
    org_id: int,
    provider: str,
    account_id: int,
    endpoint: str,
    window: Window,
) -> ProviderSyncRun | None:
    return session.scalar(
        select(ProviderSyncRun)
        .where(
            ProviderSyncRun.organization_id == org_id,
            ProviderSyncRun.provider == provider,
            ProviderSyncRun.provider_account_id == account_id,
            ProviderSyncRun.endpoint == endpoint,
            ProviderSyncRun.status == "succeeded",
            ProviderSyncRun.window_start <= window.start,
            ProviderSyncRun.window_end >= window.end,
        )
        .order_by(ProviderSyncRun.id.desc())
        .limit(1)
    )


def _credit_check_one(
    session: Session,
    org_id: int,
    provider: str,
    account_id: int,
    window: Window,
) -> CodexCreditCheck | None:
    workspace_run = _credit_run(session, org_id, provider, account_id, CODEX_COST_ENDPOINT, window)
    if workspace_run is None:
        return None
    user_run = _credit_run(session, org_id, provider, account_id, CODEX_USER_ENDPOINT, window)
    workspace_credits = Decimal("0")
    missing_price_days: set[str] = set()
    pages = session.execute(
        select(ProviderReportPage.payload, ProviderReportPage.request_params).where(
            ProviderReportPage.sync_run_id == workspace_run.id
        )
    )
    for payload, params in pages:
        workspace_credits += codex_page_credits(payload, window.start, window.end)
        schedule = [
            date.fromisoformat(row["effective_from"])
            for row in params.get(CODEX_PRICE_PARAMS_KEY, [])
            if isinstance(row, dict) and isinstance(row.get("effective_from"), str)
        ]
        for row in payload.get("data", []):
            if not isinstance(row, dict):
                continue
            started = row.get("start_time")
            totals = row.get("totals")
            if (
                isinstance(started, int)
                and not isinstance(started, bool)
                and isinstance(totals, dict)
                and Decimal(str(totals.get("credits", 0))) > 0
            ):
                day = datetime.fromtimestamp(started, tz=UTC).date()
                if window.start.date() <= day < window.end.date() and not any(
                    effective_from <= day for effective_from in schedule
                ):
                    missing_price_days.add(day.isoformat())
    user_credits = Decimal("0")
    if user_run is not None:
        for payload in session.scalars(
            select(ProviderReportPage.payload).where(ProviderReportPage.sync_run_id == user_run.id)
        ):
            user_credits += codex_page_credits(payload, window.start, window.end)
    return CodexCreditCheck(
        workspace_credits=workspace_credits,
        user_credits=user_credits,
        missing_price_days=sorted(missing_price_days),
        workspace_run_id=workspace_run.id,
        user_run_id=None if user_run is None else user_run.id,
    )


def codex_credit_check(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    account_id: int | None,
) -> CodexCreditCheck | None:
    spec = find_spec(provider)
    if spec is None or not spec.credit_pricing:
        return None
    checks = [
        check
        for _, unit_account in scope_units(session, org_id, provider, account_id)
        if (check := _credit_check_one(session, org_id, provider, unit_account, window)) is not None
    ]
    if not checks:
        return None
    return CodexCreditCheck(
        workspace_credits=sum((check.workspace_credits for check in checks), Decimal("0")),
        user_credits=sum((check.user_credits for check in checks), Decimal("0")),
        missing_price_days=sorted({day for check in checks for day in check.missing_price_days}),
        workspace_run_id=max(check.workspace_run_id for check in checks),
        user_run_id=(
            None
            if any(check.user_run_id is None for check in checks)
            else max(check.user_run_id or 0 for check in checks)
        ),
    )


def seat_total(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    account_id: int | None = None,
) -> Decimal:
    spec = find_spec(provider)
    if spec is None or not spec.seat_costs:
        return Decimal("0")
    return Decimal(
        session.scalar(
            select(func.coalesce(func.sum(SpendCostLine.amount), 0)).where(
                *cost_where(org_id, provider, window, account_id),
                SpendCostLine.cost_type == "seat",
            )
        )
        or 0
    )
