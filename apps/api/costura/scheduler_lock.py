"""Per-organization advisory locks and recovery of scheduler runs whose lease expired.

A sync worker holds the lock for one organization on a dedicated connection
(`lock_connection`) for the duration of that organization's cycle, so commits inside the
cycle do not drop it. Different organizations use different keys: two workers may sync two
organizations at the same time, and one organization is serialized because budgets and the
other derived steps write organization-scoped rows.

Lease expiry, not the lock, decides that a running row was abandoned. A queued row is
waiting for a worker and is left alone. Recovery requeues an expired lease while attempts
remain and fails the row once `attempt_count` has reached `max_attempts`.
"""

import logging
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import Connection, Engine, and_, or_, select, text
from sqlalchemy.orm import Session

from costura.models.scheduler import SchedulerRun

# High half of the per-organization advisory-lock key. The one-argument form of
# pg_advisory_lock is a different key space and is not used.
ADVISORY_LOCK_CLASS = 0x0C05
ACTIVE_RUN_STATUSES = ("queued", "running")
LEASE_EXHAUSTED = "sync stopped after the worker lease expired too many times"

log = logging.getLogger("costura.scheduler")


def organization_lock_key(organization_id: int) -> int:
    """Session advisory-lock key for one organization. Fits in a signed bigint."""
    return (ADVISORY_LOCK_CLASS << 32) + int(organization_id)


def try_organization_lock(holder: Session | Connection, organization_id: int) -> bool:
    key = organization_lock_key(organization_id)
    return bool(holder.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar())


def organization_lock_held(holder: Session | Connection, organization_id: int) -> bool:
    """True when some connection holds this organization's lock. Reads `pg_locks` and takes
    nothing: a one-bigint advisory key shows as `classid` (high half) and `objid` (low half)."""
    key = organization_lock_key(organization_id)
    held = holder.execute(
        text(
            "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted"
            " AND classid = :high AND objid = :low AND objsubid = 1"
        ),
        {"high": key >> 32, "low": key & 0xFFFFFFFF},
    ).first()
    return held is not None


def waiting_runs(session: Session) -> tuple[int, int]:
    """Queued rows that still have attempts: `(total, behind a held organization lock)`. The
    second part is waiting for another process, not for this one."""
    rows = session.execute(
        select(SchedulerRun.organization_id).where(
            SchedulerRun.status == "queued",
            SchedulerRun.attempt_count < SchedulerRun.max_attempts,
        )
    ).scalars()
    total = 0
    locked = 0
    held: dict[int, bool] = {}
    for organization_id in rows:
        total += 1
        if organization_id is None:
            continue
        if organization_id not in held:
            held[organization_id] = organization_lock_held(session, organization_id)
        locked += held[organization_id]
    return total, locked


def unlock_organization(holder: Session | Connection, organization_id: int) -> None:
    key = organization_lock_key(organization_id)
    holder.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
    holder.commit()


@contextmanager
def lock_connection(engine: Engine) -> Generator[Connection]:
    """A connection checked out for the whole cycle to hold the advisory lock. The lock is
    bound to the PostgreSQL connection, and a Session returns its connection to the pool at
    every commit; taking the lock through the working session would leave it on whichever
    pooled connection ran the first statement."""
    with engine.connect() as connection:
        yield connection


def _lease_expired():
    now = datetime.now(UTC)
    return now, or_(
        SchedulerRun.lease_expires_at.is_(None),
        SchedulerRun.lease_expires_at <= now,
    )


def recover_abandoned_runs(
    session: Session,
    *,
    organization_id: int | None = None,
    commit: bool = True,
) -> int:
    """Requeue or fail running rows whose lease has expired.

    A live worker renews `lease_expires_at`, so an unexpired lease is left running. A queued
    row stays queued unless its attempts are already spent. Returns the number of rows
    changed. `commit` is false when the caller claims in the same transaction.
    """
    now, expired = _lease_expired()
    statement = select(SchedulerRun).where(
        or_(
            and_(SchedulerRun.status == "running", expired),
            and_(
                SchedulerRun.status == "queued",
                SchedulerRun.attempt_count >= SchedulerRun.max_attempts,
            ),
        )
    )
    if organization_id is not None:
        statement = statement.where(SchedulerRun.organization_id == organization_id)
    changed = 0
    locked = statement.order_by(SchedulerRun.id).with_for_update(skip_locked=True)
    for run in session.scalars(locked):
        if run.status == "running" and run.attempt_count < run.max_attempts:
            run.status = "queued"
            run.lease_owner = None
            run.lease_expires_at = None
            run.heartbeat_at = None
            log.info(
                "requeued scheduler run %s after lease expiry (attempt %s/%s)",
                run.id,
                run.attempt_count,
                run.max_attempts,
            )
        else:
            run.status = "failed"
            run.error = LEASE_EXHAUSTED
            run.finished_at = now
            run.lease_owner = None
            run.lease_expires_at = None
            run.heartbeat_at = None
            log.info("failed scheduler run %s after the lease expired too many times", run.id)
        changed += 1
    if changed and commit:
        session.commit()
    return changed


def recover_abandoned_runs_if_unlocked(session: Session, organization_id: int) -> int:
    """Setup polls recover this organization's expired leases. A live lease is not disturbed;
    the advisory lock is not required because the lease timestamp is the liveness signal."""
    return recover_abandoned_runs(session, organization_id=organization_id)
