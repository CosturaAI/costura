"""Delete raw provider pages and finished runs past the retention settings.

`python -m costura.ops.purge` runs one pass. The worker calls the same function about
once an hour while it is polling. A retention of 0 keeps that class of row forever.

`provider_sync_runs` that spend lines, inventory snapshots or allocation rows still
reference are kept: those foreign keys are not nullable. Their raw pages are still
deleted when page retention has elapsed. Terminal scheduler runs have no such dependents.
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from costura.config import get_settings
from costura.db import SessionLocal
from costura.models import (
    ProviderApiKey,
    ProviderLimit,
    ProviderReportPage,
    ProviderSyncRun,
    ProviderUser,
    ProviderWorkspace,
    ProviderWorkspaceMember,
    SchedulerRun,
    SpendActivityLine,
    SpendAllocatedLine,
    SpendCostLine,
    SpendUsageLine,
)
from costura.ops import run

log = logging.getLogger("costura.purge")

TERMINAL_SCHEDULER_STATUSES = ("succeeded", "failed", "skipped")
COMPLETED_SYNC_STATUSES = ("succeeded", "failed")


@dataclass(frozen=True)
class PurgeCounts:
    pages: int
    scheduler_runs: int
    sync_runs: int
    sync_runs_kept: int


def _referenced_sync_run_ids(session: Session, candidate_ids: Sequence[int]) -> set[int]:
    if not candidate_ids:
        return set()
    selected = tuple(candidate_ids)
    statements = (
        select(SpendCostLine.sync_run_id).where(SpendCostLine.sync_run_id.in_(selected)),
        select(SpendUsageLine.sync_run_id).where(SpendUsageLine.sync_run_id.in_(selected)),
        select(SpendActivityLine.sync_run_id).where(SpendActivityLine.sync_run_id.in_(selected)),
        select(SpendAllocatedLine.allocation_run_id).where(
            SpendAllocatedLine.allocation_run_id.in_(selected)
        ),
        select(ProviderWorkspace.sync_run_id).where(ProviderWorkspace.sync_run_id.in_(selected)),
        select(ProviderUser.sync_run_id).where(ProviderUser.sync_run_id.in_(selected)),
        select(ProviderApiKey.sync_run_id).where(ProviderApiKey.sync_run_id.in_(selected)),
        select(ProviderLimit.sync_run_id).where(ProviderLimit.sync_run_id.in_(selected)),
        select(ProviderWorkspaceMember.sync_run_id).where(
            ProviderWorkspaceMember.sync_run_id.in_(selected)
        ),
    )
    found: set[int] = set()
    for statement in statements:
        found.update(row_id for row_id in session.scalars(statement) if row_id is not None)
    return found


def _delete_count(session: Session, statement) -> int:
    result = session.execute(statement)
    count = result.rowcount  # ty: ignore[unresolved-attribute]
    return int(count) if count is not None and count >= 0 else 0


def purge(
    session: Session,
    *,
    now: datetime | None = None,
    page_days: int | None = None,
    run_days: int | None = None,
    commit: bool = True,
) -> PurgeCounts:
    """Delete rows older than the retention windows and return how many went away.

    `page_days` and `run_days` override the settings (tests). Zero keeps that class.
    Queued and running scheduler rows, and provider sync runs that are still `running`
    or still referenced by the ledger, are left in place.
    """
    settings = get_settings()
    page_retention = settings.costura_raw_page_retention_days if page_days is None else page_days
    run_retention = settings.costura_run_retention_days if run_days is None else run_days
    if page_retention < 0 or run_retention < 0:
        raise ValueError("retention days must be zero or greater")
    moment = now or datetime.now(UTC)
    pages = 0
    scheduler_runs = 0
    sync_runs = 0
    sync_runs_kept = 0
    if page_retention > 0:
        cutoff = moment - timedelta(days=page_retention)
        pages = _delete_count(
            session,
            delete(ProviderReportPage).where(ProviderReportPage.fetched_at < cutoff),
        )
    if run_retention > 0:
        cutoff = moment - timedelta(days=run_retention)
        scheduler_runs = _delete_count(
            session,
            delete(SchedulerRun).where(
                SchedulerRun.status.in_(TERMINAL_SCHEDULER_STATUSES),
                SchedulerRun.finished_at.is_not(None),
                SchedulerRun.finished_at < cutoff,
            ),
        )
        candidate_ids = list(
            session.scalars(
                select(ProviderSyncRun.id).where(
                    ProviderSyncRun.status.in_(COMPLETED_SYNC_STATUSES),
                    ProviderSyncRun.finished_at.is_not(None),
                    ProviderSyncRun.finished_at < cutoff,
                )
            )
        )
        referenced = _referenced_sync_run_ids(session, candidate_ids)
        sync_runs_kept = len(referenced)
        deletable = [row_id for row_id in candidate_ids if row_id not in referenced]
        if deletable:
            sync_runs = _delete_count(
                session,
                delete(ProviderSyncRun).where(ProviderSyncRun.id.in_(tuple(deletable))),
            )
    if commit:
        session.commit()
    return PurgeCounts(
        pages=pages,
        scheduler_runs=scheduler_runs,
        sync_runs=sync_runs,
        sync_runs_kept=sync_runs_kept,
    )


def _queue_depth(session: Session) -> tuple[int, int]:
    rows = dict(
        session.execute(
            select(SchedulerRun.status, func.count())
            .where(SchedulerRun.status.in_(("queued", "running")))
            .group_by(SchedulerRun.status)
        ).all()
    )
    return int(rows.get("queued", 0)), int(rows.get("running", 0))


def purge_and_log(session: Session | None = None) -> PurgeCounts:
    """One retention pass plus an audit line with the queue depth left behind."""
    owns_session = session is None
    bound = session or SessionLocal()
    try:
        counts = purge(bound)
        queued, running = _queue_depth(bound)
        log.info(
            "retention purge pages=%s scheduler_runs=%s sync_runs=%s sync_runs_kept=%s "
            "scheduler_queued=%s scheduler_running=%s",
            counts.pages,
            counts.scheduler_runs,
            counts.sync_runs,
            counts.sync_runs_kept,
            queued,
            running,
        )
        return counts
    finally:
        if owns_session:
            bound.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="costura.ops.purge", description=__doc__)
    parser.parse_args(argv)

    def operation() -> int:

        counts = purge_and_log()
        print(
            f"pages={counts.pages} scheduler_runs={counts.scheduler_runs} "
            f"sync_runs={counts.sync_runs} sync_runs_kept={counts.sync_runs_kept}"
        )
        return 0

    return run(operation)


if __name__ == "__main__":
    sys.exit(main())
