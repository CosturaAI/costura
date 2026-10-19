"""Whether the allocated rows of the latest succeeded allocation run still add up to the cost.

The check is per provider account: over a provider it adds the accounts up and is
unknown (None) when an account with cost lines has no covering run."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import (
    ProviderSyncRun,
    SpendAllocatedLine,
    SpendCostLine,
    SpendUsageLine,
)
from costura.models.allocation import ALLOCATION_ENDPOINT
from costura.spend.ledger import (
    has_cost_amount,
    in_window,
    scope_units,
)
from costura.spend.window import Window


@dataclass
class AllocationCheck:
    """Latest succeeded allocation run covering the window, against the cost total."""

    run_id: int
    allocated_total: Decimal
    unallocated_total: Decimal
    unallocated_by_reason: dict[str, Decimal]

    def delta(self, costura_total: Decimal) -> Decimal:
        return costura_total - (self.allocated_total + self.unallocated_total)


def allocation_check(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    account_id: int | None = None,
) -> AllocationCheck | None:
    """Current allocation for every cost-bearing account in the effective scope.

    An account is current only when its latest covering allocation run succeeded, every
    allocation row in the window belongs to that run, and the run is newer than the cost and
    usage rows it derived. One missing or stale account makes the complete scope unavailable.
    """
    units = [
        (name, unit_account)
        for name, unit_account in scope_units(session, org_id, provider, account_id)
        if has_cost_amount(session, org_id, name, window, unit_account)
    ]
    if not units:
        return None
    checks: list[AllocationCheck] = []
    for name, unit_account in units:
        check = allocation_check_one(session, org_id, name, unit_account, window)
        if check is None:
            return None
        checks.append(check)
    if len(checks) > 1:
        by_reason: dict[str, Decimal] = {}
        for check in checks:
            for reason, amount in check.unallocated_by_reason.items():
                by_reason[reason] = by_reason.get(reason, Decimal("0")) + amount
        return AllocationCheck(
            run_id=max(c.run_id for c in checks),
            allocated_total=sum((c.allocated_total for c in checks), Decimal("0")),
            unallocated_total=sum((c.unallocated_total for c in checks), Decimal("0")),
            unallocated_by_reason=by_reason,
        )
    return checks[0]


def allocation_covers(session: Session, org_id: int, provider: str, window: Window) -> bool:
    """Whether every month the window touches has a current allocation for its cost.

    Allocation runs one calendar month at a time, so a range across months is checked month by
    month. A month without cost needs no allocation; a window without any cost is not covered.
    """
    covered = False
    for part in window.month_parts():
        if allocation_check(session, org_id, provider, part) is not None:
            covered = True
        elif any(
            has_cost_amount(session, org_id, name, part, unit_account)
            for name, unit_account in scope_units(session, org_id, provider, None)
        ):
            return False
    return covered


def allocation_check_one(
    session: Session, org_id: int, provider: str, account_id: int, window: Window
) -> AllocationCheck | None:
    run_id = session.scalar(
        select(ProviderSyncRun.id)
        .where(
            ProviderSyncRun.organization_id == org_id,
            ProviderSyncRun.provider == provider,
            ProviderSyncRun.provider_account_id == account_id,
            ProviderSyncRun.endpoint == ALLOCATION_ENDPOINT,
            ProviderSyncRun.window_start <= window.start,
            ProviderSyncRun.window_end >= window.end,
        )
        .order_by(ProviderSyncRun.id.desc())
        .limit(1)
    )
    if run_id is None:
        return None
    run = session.get(ProviderSyncRun, run_id)
    if run is None or run.status != "succeeded":
        return None
    latest_input_run = max(
        (
            session.scalar(
                select(func.max(table.sync_run_id)).where(
                    table.organization_id == org_id,
                    table.provider == provider,
                    table.provider_account_id == account_id,
                    in_window(table.period_start, window),
                )
            )
            or 0
            for table in (SpendCostLine, SpendUsageLine)
        ),
        default=0,
    )
    if run_id <= latest_input_run:
        return None
    allocation_run_ids = set(
        session.scalars(
            select(SpendAllocatedLine.allocation_run_id).where(
                SpendAllocatedLine.organization_id == org_id,
                SpendAllocatedLine.provider == provider,
                SpendAllocatedLine.provider_account_id == account_id,
                in_window(SpendAllocatedLine.period_start, window),
            )
        )
    )
    if allocation_run_ids != {run_id}:
        return None
    rows = session.execute(
        select(SpendAllocatedLine.unallocated_reason, func.sum(SpendAllocatedLine.amount))
        .where(
            SpendAllocatedLine.organization_id == org_id,
            SpendAllocatedLine.provider == provider,
            SpendAllocatedLine.allocation_run_id == run_id,
            in_window(SpendAllocatedLine.period_start, window),
        )
        .group_by(SpendAllocatedLine.unallocated_reason)
    ).all()
    allocated = Decimal("0")
    by_reason: dict[str, Decimal] = {}
    for reason, amount in rows:
        if reason is None:
            allocated += Decimal(amount)
        else:
            by_reason[reason] = Decimal(amount)
    return AllocationCheck(
        run_id=run_id,
        allocated_total=allocated,
        unallocated_total=sum(by_reason.values(), Decimal("0")),
        unallocated_by_reason=by_reason,
    )
