"""The latest scheduler run and the latest provider sync run of an organization, per provider
and per account, read in grouped queries so the setup and provider pages cost the same for
one account as for many."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import ProviderSyncRun
from costura.models.scheduler import SchedulerRun


@dataclass(frozen=True)
class LatestRuns:
    by_account: dict[tuple[str, int], SchedulerRun]
    by_provider: dict[str, SchedulerRun]
    sync_by_provider: dict[str, ProviderSyncRun]


def latest_runs(session: Session, org_id: int, providers: Sequence[str]) -> LatestRuns:
    per_account = (
        select(func.max(SchedulerRun.id))
        .where(
            SchedulerRun.organization_id == org_id,
            SchedulerRun.provider.in_(providers),
            SchedulerRun.provider_account_id.is_not(None),
        )
        .group_by(SchedulerRun.provider, SchedulerRun.provider_account_id)
    )
    per_provider = (
        select(func.max(SchedulerRun.id))
        .where(SchedulerRun.organization_id == org_id, SchedulerRun.provider.in_(providers))
        .group_by(SchedulerRun.provider)
    )
    runs = {
        run.id: run
        for run in session.scalars(
            select(SchedulerRun).where(
                SchedulerRun.id.in_(per_account.union(per_provider).scalar_subquery())
            )
        )
    }
    by_account: dict[tuple[str, int], SchedulerRun] = {}
    by_provider: dict[str, SchedulerRun] = {}
    for run in sorted(runs.values(), key=lambda row: row.id):
        if run.provider_account_id is not None:
            by_account[(run.provider, run.provider_account_id)] = run
        by_provider[run.provider] = run
    latest_sync = (
        select(func.max(ProviderSyncRun.id))
        .where(ProviderSyncRun.organization_id == org_id, ProviderSyncRun.provider.in_(providers))
        .group_by(ProviderSyncRun.provider)
    )
    sync_by_provider = {
        run.provider: run
        for run in session.scalars(
            select(ProviderSyncRun).where(ProviderSyncRun.id.in_(latest_sync.scalar_subquery()))
        )
    }
    return LatestRuns(
        by_account=by_account, by_provider=by_provider, sync_by_provider=sync_by_provider
    )
