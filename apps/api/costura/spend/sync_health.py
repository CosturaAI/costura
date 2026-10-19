"""Connected provider accounts whose spend stopped arriving: a refused key, a failed latest
cost sync, no succeeded cost sync for `STALE_DAYS`, or imports that succeed but have reported
no spend for `SILENT_DAYS` after the account spent in the month before."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import ProviderAccount, ProviderCredential, ProviderSyncRun, SpendCostLine
from costura.providers.registry import get_spec, resolve_scope

STALE_DAYS = 2
SILENT_DAYS = 3
AVERAGE_DAYS = 30


@dataclass(frozen=True)
class SyncHealth:
    account: ProviderAccount
    reason: str
    last_success: datetime | None
    dollars_at_risk: Decimal
    detected_at: datetime


def unhealthy_accounts(
    session: Session, org_id: int, provider: str, today: date | None = None
) -> list[SyncHealth]:
    """Accounts with a stored key and no disconnection whose cost import needs a person."""
    today = today or datetime.now(UTC).date()
    names = resolve_scope(provider)
    rows = session.execute(
        select(ProviderAccount, ProviderCredential)
        .join(ProviderCredential, ProviderCredential.account_id == ProviderAccount.id)
        .where(
            ProviderAccount.organization_id == org_id,
            ProviderAccount.provider.in_(names),
            ProviderAccount.disconnected_at.is_(None),
        )
        .order_by(ProviderAccount.id)
    ).all()
    found: list[SyncHealth] = []
    for account, credential in rows:
        endpoint = get_spec(account.provider).cost_endpoint
        runs = list(
            session.scalars(
                select(ProviderSyncRun)
                .where(
                    ProviderSyncRun.organization_id == org_id,
                    ProviderSyncRun.provider_account_id == account.id,
                    ProviderSyncRun.endpoint == endpoint,
                    ProviderSyncRun.status.in_(("succeeded", "failed")),
                )
                .order_by(ProviderSyncRun.id.desc())
                .limit(20)
            )
        )
        successes = [r for r in runs if r.status == "succeeded" and r.finished_at]
        last_success = max((r.finished_at for r in successes if r.finished_at), default=None)
        newest = runs[0] if runs else None
        reason = None
        if credential.last_error:
            reason = "the provider refused the key"
        elif newest is not None and newest.status == "failed":
            reason = "the latest cost import failed"
        elif last_success is None:
            if credential.created_at.date() < today - timedelta(days=1):
                reason = "no cost import has succeeded since the key was connected"
        elif last_success.date() < today - timedelta(days=STALE_DAYS):
            reason = f"no cost import has succeeded since {last_success.date().isoformat()}"
        else:
            silent = _silent_since(session, org_id, account, today)
            if silent is not None:
                reason = f"the provider has reported no spend since {silent.isoformat()}"
                last_success = datetime.combine(silent, datetime.min.time(), UTC)
        if reason is None:
            continue
        found.append(
            SyncHealth(
                account=account,
                reason=reason,
                last_success=last_success,
                dollars_at_risk=_missed_spend(session, org_id, account, today, last_success),
                detected_at=(newest.finished_at if newest and newest.finished_at else None)
                or credential.created_at,
            )
        )
    return found


def _silent_since(
    session: Session, org_id: int, account: ProviderAccount, today: date
) -> date | None:
    """The last day with spend when it is `SILENT_DAYS` or more before the last complete day
    and the account spent in the 30 days before it; None otherwise."""
    last_day = session.scalar(
        select(func.max(SpendCostLine.period_start)).where(
            SpendCostLine.organization_id == org_id,
            SpendCostLine.provider_account_id == account.id,
            SpendCostLine.amount > 0,
        )
    )
    if last_day is None:
        return None
    last = last_day.date()
    complete = today - timedelta(days=1)
    if (complete - last).days < SILENT_DAYS:
        return None
    return last if (today - last).days <= AVERAGE_DAYS + SILENT_DAYS else None


def _missed_spend(
    session: Session,
    org_id: int,
    account: ProviderAccount,
    today: date,
    last_success: datetime | None,
) -> Decimal:
    """The account's daily average over the last 30 days times the days since the last
    success: the spend the queue is not seeing."""
    start = datetime.combine(today - timedelta(days=AVERAGE_DAYS), datetime.min.time(), UTC)
    total = session.scalar(
        select(func.coalesce(func.sum(SpendCostLine.amount), 0)).where(
            SpendCostLine.organization_id == org_id,
            SpendCostLine.provider_account_id == account.id,
            SpendCostLine.period_start >= start,
        )
    )
    missed = max(1, (today - last_success.date()).days if last_success else 1)
    return (Decimal(total or 0) / AVERAGE_DAYS * missed).quantize(Decimal("0.01"))
