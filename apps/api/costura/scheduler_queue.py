"""Persistence and idempotency of the sync queue.

The organization row is locked so enqueue and reset cannot interleave. Interactive triggers
refuse when that account already has a queued or running row. The daily trigger is idempotent
for the UTC day: a second enqueue returns the existing row.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from costura import credentials
from costura.config import Settings, get_settings
from costura.errors import DomainError
from costura.models.organization import Organization
from costura.models.scheduler import SchedulerRun
from costura.scheduler_lock import ACTIVE_RUN_STATUSES
from costura.sync_cycle import Trigger

PRIORITY_INTERACTIVE = 10
PRIORITY_DAILY = 100


class SchedulerBusy(RuntimeError, DomainError):
    """The account already has a queued or running sync. `status` is 409."""

    status = 409
    code = "sync_already_queued"


def idempotency_key(
    org_id: int,
    provider: str,
    account_id: int | None,
    trigger: str,
    day: date,
) -> str:
    """One daily row per organization, provider, account, trigger and UTC day."""
    account = "none" if account_id is None else str(account_id)
    return f"{org_id}:{provider}:{account}:{trigger}:{day.isoformat()}"


def _priority_for(trigger: Trigger) -> int:
    return PRIORITY_DAILY if trigger == "scheduler" else PRIORITY_INTERACTIVE


def _active_run(
    session: Session, org_id: int, provider: str, account_id: int | None
) -> SchedulerRun | None:
    statement = select(SchedulerRun).where(
        SchedulerRun.organization_id == org_id,
        SchedulerRun.provider == provider,
        SchedulerRun.status.in_(ACTIVE_RUN_STATUSES),
    )
    if account_id is None:
        statement = statement.where(SchedulerRun.provider_account_id.is_(None))
    else:
        statement = statement.where(SchedulerRun.provider_account_id == account_id)
    return session.scalar(statement.order_by(SchedulerRun.id).limit(1))


def enqueue_runs(
    session: Session,
    org_id: int,
    providers: Sequence[str],
    *,
    trigger: Trigger,
    settings: Settings | None = None,
    account_ids: Mapping[str, Sequence[int | None]] | None = None,
    on: date | None = None,
) -> list[SchedulerRun]:
    """Add one queued row per account and return the rows; the caller commits. Does not
    execute them. The rows go in under a savepoint, so a concurrent daily enqueue costs
    only these rows, never the caller's earlier writes.

    The organization row is locked so enqueue and reset cannot interleave. Interactive
    triggers refuse when that account already has a queued or running row. The daily
    trigger is idempotent for the UTC day (`on` overrides the day in tests): a second
    enqueue returns the existing row. A provider with no connected account gets one row
    without an account, which the worker records as skipped for want of a key.
    """
    settings = settings or get_settings()
    day = on or datetime.now(UTC).date()
    session.scalar(select(Organization).where(Organization.id == org_id).with_for_update())
    runs: list[SchedulerRun] = []
    fresh: list[SchedulerRun] = []
    for provider in providers:
        if account_ids is not None and provider in account_ids:
            ids: list[int | None] = list(account_ids[provider])
        else:
            credentials.environment_account(session, settings, org_id, provider)
            ids = [
                c.account_id
                for c in credentials.connected_accounts(session, settings, org_id, provider)
            ]
        for account_id in ids or [None]:
            key = (
                idempotency_key(org_id, provider, account_id, trigger, day)
                if trigger == "scheduler"
                else None
            )
            if key is not None:
                existing = session.scalar(
                    select(SchedulerRun).where(SchedulerRun.idempotency_key == key)
                )
                if existing is not None:
                    runs.append(existing)
                    continue
            elif (active := _active_run(session, org_id, provider, account_id)) is not None:
                raise SchedulerBusy(
                    f"sync already {active.status} for {active.provider} "
                    f"(scheduler run {active.id})"
                )
            run = SchedulerRun(
                organization_id=org_id,
                provider=provider,
                provider_account_id=account_id,
                trigger=trigger,
                status="queued",
                steps=[],
                priority=_priority_for(trigger),
                idempotency_key=key,
            )
            fresh.append(run)
            runs.append(run)
    keys = [run.idempotency_key for run in runs]
    try:
        with session.begin_nested():
            session.add_all(fresh)
    except IntegrityError:
        reloaded: list[SchedulerRun] = []
        for key in keys:
            if key is None:
                raise
            found = session.scalar(select(SchedulerRun).where(SchedulerRun.idempotency_key == key))
            if found is None:
                raise
            reloaded.append(found)
        return reloaded
    return runs
