"""What the getting-started card reads beyond the provider list: credit prices still missing,
the newest scheduler run per account, the worker's last heartbeat, and the dismissal."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import CreditPrice, Organization, ProviderAccount, SchedulerRun, WorkerHeartbeat
from costura.providers.registry import PROVIDERS


def pricing_missing(session: Session, org_id: int, connected: set[str]) -> bool:
    """True when a connected provider priced per account (`setup_pricing`) has an account
    without a credit price."""
    priced_providers = {name for name, spec in PROVIDERS.items() if spec.setup_pricing}
    if not priced_providers & connected:
        return False
    account_ids = list(
        session.scalars(
            select(ProviderAccount.id).where(
                ProviderAccount.organization_id == org_id,
                ProviderAccount.provider.in_(priced_providers),
            )
        )
    )
    if not account_ids:
        return True
    priced = session.scalar(
        select(func.count())
        .select_from(CreditPrice)
        .where(
            CreditPrice.organization_id == org_id,
            CreditPrice.provider_account_id.in_(account_ids),
        )
    )
    return int(priced or 0) < len(account_ids)


def latest_scheduler_runs(session: Session, org_id: int) -> list[SchedulerRun]:
    """The newest scheduler run of each (provider, account), in provider and account order."""
    latest = (
        select(func.max(SchedulerRun.id))
        .where(SchedulerRun.organization_id == org_id)
        .group_by(SchedulerRun.provider, SchedulerRun.provider_account_id)
    )
    return list(
        session.scalars(
            select(SchedulerRun)
            .where(SchedulerRun.id.in_(latest))
            .order_by(SchedulerRun.provider, SchedulerRun.provider_account_id)
        )
    )


def worker_seen_at(session: Session) -> datetime | None:
    return session.scalar(
        select(func.max(WorkerHeartbeat.last_seen_at)).where(WorkerHeartbeat.role == "worker")
    )


def dismiss(session: Session, org: Organization) -> None:
    """Hide the card for good; a second call keeps the first timestamp."""
    if org.onboarding_dismissed_at is None:
        org.onboarding_dismissed_at = datetime.now(UTC)
        session.flush()


def account_labels(session: Session, account_ids: set[int]) -> dict[int, str]:
    if not account_ids:
        return {}
    rows = session.execute(
        select(ProviderAccount.id, ProviderAccount.label).where(ProviderAccount.id.in_(account_ids))
    )
    return {int(account_id): str(label) for account_id, label in rows}
