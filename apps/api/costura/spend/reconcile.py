"""Compare Costura's stored spend with a figure the provider reports elsewhere.

Everything here reads `spend_cost_lines`, `spend_usage_lines`, `spend_allocated_lines` and the
raw pages for one provider and one `[start, end)` window. No pricing is applied; token totals
are context and the allocation check confirms the allocated rows still add up to the cost.

Runs (report pages, allocation, per-key money) are per provider account: a check
over a provider adds its accounts up and is unknown when any account with cost lines has no
covering run. `account_id` narrows every reader to one account.

The readers and checks live in `ledger`, `allocation_check`, `key_check` and `provider_totals`;
this module composes them into one `ReconcileReport`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import (
    ProviderSyncRun,
    SpendUsageLine,
)
from costura.providers.registry import find_spec, get_spec
from costura.spend.allocation_check import (
    AllocationCheck,
    allocation_check,
)
from costura.spend.key_check import (
    KeyCheck,
    key_check,
    key_check_supported,
)
from costura.spend.ledger import (
    BreakdownRow,
    breakdown,
    costura_total,
    in_window,
    scope_units,
    token_totals,
)
from costura.spend.money import to_percent, within_cent
from costura.spend.provider_totals import (
    CodexCreditCheck,
    codex_credit_check,
    provider_total_of_latest_run,
    raw_total_of_latest_run,
    seat_total,
)
from costura.spend.scope import account_clause
from costura.spend.window import Window


@dataclass(frozen=True)
class ActivityCoverage:
    covered_families: list[str]
    missing_families: list[str]

    @property
    def complete(self) -> bool:
        return not self.missing_families


@dataclass
class ReconcileReport:
    provider: str
    window: Window
    reported_total: Decimal
    costura_total: Decimal
    currency: str | None
    breakdown_dimension: str
    breakdown: list[BreakdownRow]
    raw_total_latest_run: Decimal | None
    latest_run_id: int | None
    provider_total_latest_run: Decimal | None = None
    provider_total_run_id: int | None = None
    derived_seat_total: Decimal = Decimal("0")
    token_totals: dict[str, int] = field(default_factory=dict)
    allocation: AllocationCheck | None = None
    key_check: KeyCheck | None = None
    key_check_supported: bool = False
    activity_coverage: ActivityCoverage | None = None
    codex_credit_check: CodexCreditCheck | None = None
    # The account the report is narrowed to; None for every account of the provider.
    account_id: int | None = None
    data_refreshed_at: datetime | None = None
    user_attributed_total: Decimal | None = None

    @property
    def delta(self) -> Decimal:
        return self.costura_total - self.reported_total

    @property
    def delta_percent(self) -> Decimal | None:
        if self.reported_total == 0:
            return None
        return to_percent(self.delta / self.reported_total * 100)

    @property
    def raw_vs_normalized_delta(self) -> Decimal | None:
        if self.raw_total_latest_run is None:
            return None
        return self.costura_total - self.derived_seat_total - self.raw_total_latest_run

    @property
    def matches(self) -> bool:
        credits_match = self.codex_credit_check is None or self.codex_credit_check.ok
        return within_cent(self.delta) and credits_match

    @property
    def provider_delta(self) -> Decimal | None:
        """costura_total minus the ungrouped provider total (cost_total run), or None without
        a run."""
        if self.provider_total_latest_run is None:
            return None
        return self.costura_total - self.derived_seat_total - self.provider_total_latest_run

    @property
    def provider_matches(self) -> bool | None:
        delta = self.provider_delta
        if delta is None:
            return None
        return within_cent(delta)

    @property
    def user_unattributed_total(self) -> Decimal | None:
        if self.user_attributed_total is None:
            return None
        return self.costura_total - self.user_attributed_total


def activity_coverage(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    account_id: int | None = None,
) -> ActivityCoverage | None:
    spec = find_spec(provider)
    families = spec.activity_families if spec is not None else ()
    if not families:
        return None
    units = scope_units(session, org_id, provider, account_id)
    endpoints = {f"usage_{family}": family for family in families}
    succeeded = set(
        session.execute(
            select(ProviderSyncRun.provider_account_id, ProviderSyncRun.endpoint)
            .where(
                ProviderSyncRun.organization_id == org_id,
                ProviderSyncRun.provider == provider,
                ProviderSyncRun.endpoint.in_(endpoints),
                ProviderSyncRun.status == "succeeded",
                ProviderSyncRun.window_start <= window.start,
                ProviderSyncRun.window_end >= window.end,
            )
            .distinct()
        )
    )
    covered = [
        family
        for endpoint, family in endpoints.items()
        if units
        and all(
            unit_account is not None and (unit_account, endpoint) in succeeded
            for _, unit_account in units
        )
    ]
    return ActivityCoverage(
        covered_families=covered,
        missing_families=[family for family in families if family not in covered],
    )


def reconcile(
    session: Session,
    *,
    org_id: int,
    provider: str,
    window: Window,
    reported_total: Decimal,
    dimension: str = "day",
    account_id: int | None = None,
) -> ReconcileReport:
    total, currency = costura_total(session, org_id, provider, window, account_id)
    run_id, raw_total = raw_total_of_latest_run(session, org_id, provider, window, account_id)
    total_run_id, provider_total = provider_total_of_latest_run(
        session, org_id, provider, window, account_id
    )
    seats = seat_total(session, org_id, provider, window, account_id)
    tokens = token_totals(session, org_id, provider, window, account_id)
    user_total = _user_attributed_total(session, org_id, provider, window, account_id)
    return ReconcileReport(
        provider=provider,
        window=window,
        reported_total=reported_total,
        costura_total=total,
        currency=currency,
        breakdown_dimension=dimension,
        breakdown=breakdown(session, org_id, provider, window, dimension, account_id),
        raw_total_latest_run=raw_total,
        latest_run_id=run_id,
        provider_total_latest_run=provider_total,
        provider_total_run_id=total_run_id,
        derived_seat_total=seats,
        token_totals=tokens,
        allocation=allocation_check(session, org_id, provider, window, account_id),
        key_check=key_check(session, org_id, provider, window, account_id),
        key_check_supported=key_check_supported(provider),
        activity_coverage=activity_coverage(session, org_id, provider, window, account_id),
        codex_credit_check=codex_credit_check(session, org_id, provider, window, account_id),
        account_id=account_id,
        data_refreshed_at=_data_watermark(session, org_id, provider, window, account_id),
        user_attributed_total=user_total,
    )


def _user_attributed_total(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    account_id: int | None,
) -> Decimal | None:
    spec = find_spec(provider)
    if spec is None or not spec.user_attributed:
        return None
    value = session.scalar(
        select(func.sum(SpendUsageLine.amount)).where(
            SpendUsageLine.organization_id == org_id,
            SpendUsageLine.provider == provider,
            account_clause(SpendUsageLine.provider_account_id, account_id),
            in_window(SpendUsageLine.period_start, window),
            SpendUsageLine.amount.is_not(None),
        )
    )
    return Decimal(value or 0)


def _data_watermark(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    account_id: int | None,
) -> datetime | None:
    spec = find_spec(provider)
    if spec is None or not spec.user_attributed:
        return None
    endpoints = get_spec(provider).data_endpoints
    latest = (
        select(func.max(ProviderSyncRun.id))
        .where(
            ProviderSyncRun.organization_id == org_id,
            ProviderSyncRun.provider == provider,
            ProviderSyncRun.endpoint.in_(endpoints),
            ProviderSyncRun.status == "succeeded",
            ProviderSyncRun.window_start <= window.start,
            ProviderSyncRun.window_end >= window.end,
        )
        .group_by(ProviderSyncRun.provider_account_id, ProviderSyncRun.endpoint)
    )
    refreshed = {
        (account, endpoint): value
        for account, endpoint, value in session.execute(
            select(
                ProviderSyncRun.provider_account_id,
                ProviderSyncRun.endpoint,
                ProviderSyncRun.data_refreshed_at,
            ).where(ProviderSyncRun.id.in_(latest.scalar_subquery()))
        )
    }
    values: list[datetime] = []
    for _, unit_account in scope_units(session, org_id, provider, account_id):
        for endpoint in endpoints:
            value = refreshed.get((unit_account, endpoint)) if unit_account is not None else None
            if value is None:
                return None
            values.append(value)
    return min(values) if values else None
