"""Per-API-key money: the cost the provider attributes to each key against the allocated rows."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import (
    ProviderReportPage,
    ProviderSyncRun,
    SpendAllocatedLine,
)
from costura.providers.registry import get_spec
from costura.spend.allocation_check import allocation_check_one
from costura.spend.ledger import (
    has_cost_amount,
    in_window,
    scope_units,
)
from costura.spend.money import within_cent
from costura.spend.scope import is_all
from costura.spend.window import Window


@dataclass(frozen=True)
class KeyDelta:
    api_key_id: str
    provider_amount: Decimal
    allocated_amount: Decimal

    @property
    def delta(self) -> Decimal:
        return self.allocated_amount - self.provider_amount


@dataclass
class KeyCheck:
    """The provider's own per-key money (latest succeeded `key_endpoint` run covering the
    window) against the allocated rows per key, one cent of tolerance per key."""

    run_id: int
    keys_compared: int
    keys_off: list[KeyDelta]
    provider_total: Decimal
    allocated_total: Decimal

    @property
    def ok(self) -> bool:
        return not self.keys_off


def key_check_supported(provider: str) -> bool:
    """Whether one concrete provider publishes per-key money; `all` never does."""
    return not is_all(provider) and get_spec(provider).key_endpoint is not None


def key_check(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    account_id: int | None = None,
) -> KeyCheck | None:
    """Per-key comparison for providers with a `key_endpoint`: the latest succeeded run
    covering the window, summed per key over its raw pages, against the current allocation's
    allocated rows per key, account by account. Money the provider ties to no key is left out
    on both sides. None when the provider has no such endpoint, or when any cost-bearing
    account has no covering run or no current allocation."""
    if not key_check_supported(provider):
        return None
    units = [
        (name, unit_account)
        for name, unit_account in scope_units(session, org_id, provider, account_id)
        if has_cost_amount(session, org_id, name, window, unit_account)
    ]
    checks: list[KeyCheck] = []
    for _, unit_account in units:
        check = _key_check_one(session, org_id, provider, unit_account, window)
        if check is None:
            return None
        checks.append(check)
    if not checks:
        return None
    if len(checks) == 1:
        return checks[0]
    keys_off = [k for c in checks for k in c.keys_off]
    keys_off.sort(key=lambda k: abs(k.delta), reverse=True)
    return KeyCheck(
        run_id=max(c.run_id for c in checks),
        keys_compared=sum(c.keys_compared for c in checks),
        keys_off=keys_off,
        provider_total=sum((c.provider_total for c in checks), Decimal("0")),
        allocated_total=sum((c.allocated_total for c in checks), Decimal("0")),
    )


def _key_check_one(
    session: Session, org_id: int, provider: str, account_id: int, window: Window
) -> KeyCheck | None:
    spec = get_spec(provider)
    assert spec.key_endpoint is not None and spec.key_amounts is not None
    allocation = allocation_check_one(session, org_id, provider, account_id, window)
    if allocation is None:
        return None
    run_id = session.scalar(
        select(ProviderSyncRun.id)
        .where(
            ProviderSyncRun.organization_id == org_id,
            ProviderSyncRun.provider == provider,
            ProviderSyncRun.provider_account_id == account_id,
            ProviderSyncRun.endpoint == spec.key_endpoint,
            ProviderSyncRun.status == "succeeded",
            ProviderSyncRun.window_start <= window.start,
            ProviderSyncRun.window_end >= window.end,
        )
        .order_by(ProviderSyncRun.id.desc())
        .limit(1)
    )
    if run_id is None:
        return None
    provider_by_key: dict[str, Decimal] = {}
    for payload in session.scalars(
        select(ProviderReportPage.payload).where(ProviderReportPage.sync_run_id == run_id)
    ):
        for key_id, amount in spec.key_amounts(payload, window.start, window.end).items():
            if key_id is None:
                continue
            provider_by_key[key_id] = provider_by_key.get(key_id, Decimal("0")) + amount
    rows = session.execute(
        select(SpendAllocatedLine.api_key_id, func.sum(SpendAllocatedLine.amount))
        .where(
            SpendAllocatedLine.organization_id == org_id,
            SpendAllocatedLine.provider == provider,
            SpendAllocatedLine.provider_account_id == account_id,
            SpendAllocatedLine.allocation_run_id == allocation.run_id,
            SpendAllocatedLine.unallocated_reason.is_(None),
            SpendAllocatedLine.api_key_id.is_not(None),
            in_window(SpendAllocatedLine.period_start, window),
        )
        .group_by(SpendAllocatedLine.api_key_id)
    ).all()
    allocated_by_key = {key_id: Decimal(amount) for key_id, amount in rows if key_id is not None}
    keys_off = [
        KeyDelta(
            api_key_id=key_id,
            provider_amount=provider_by_key.get(key_id, Decimal("0")),
            allocated_amount=allocated_by_key.get(key_id, Decimal("0")),
        )
        for key_id in sorted(set(provider_by_key) | set(allocated_by_key))
    ]
    keys_off = [k for k in keys_off if not within_cent(k.delta)]
    keys_off.sort(key=lambda k: abs(k.delta), reverse=True)
    return KeyCheck(
        run_id=run_id,
        keys_compared=len(set(provider_by_key) | set(allocated_by_key)),
        keys_off=keys_off,
        provider_total=sum(provider_by_key.values(), Decimal("0")),
        allocated_total=sum(allocated_by_key.values(), Decimal("0")),
    )
