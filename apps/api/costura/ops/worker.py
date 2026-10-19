"""Sync worker: `python -m costura.ops.worker [--once]`.

Polls `scheduler_runs`, claims one queued row (or a row whose lease has expired) with
`SELECT … FOR UPDATE SKIP LOCKED`, and runs that account's sync cycle. The claim sets
`lease_owner`, `lease_expires_at` and `heartbeat_at` and moves the row from queued to
running. A background heartbeat extends the lease until the cycle finishes; success or
failure then writes the terminal status and clears the lease.

Concurrency is one run at a time in this process, with a PostgreSQL advisory lock scoped
to the organization (see `costura.scheduler_lock`). The lock is not global: another
worker can claim a different organization's row while this one is busy. Runs of the same
organization stay serialized because allocation, detection, projection and budgets write
organization-scoped rows. An organization whose lock is already held is left queued for
a later pass. Expired leases are requeued until `max_attempts`, then failed.

`--once` drains the rows that are claimable now and exits. The API never claims or runs
these rows; it only inserts them. Between passes, about once an hour, the process also
deletes raw pages and terminal runs past retention (`costura.ops.purge`), and about once a
minute posts new signals to the organizations' webhooks (`costura.delivery`). `--once` does
neither.
"""

import argparse
import logging
import os
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, defer

from costura import credentials
from costura.config import get_settings
from costura.db import SessionLocal, get_engine
from costura.models.organization import Organization
from costura.models.scheduler import SchedulerRun
from costura.ops import OperationError, run
from costura.ops.purge import purge_and_log
from costura.ops.scheduler import _report_cycles
from costura.scheduler_lock import (
    lock_connection,
    recover_abandoned_runs,
    try_organization_lock,
    unlock_organization,
)
from costura.sync_cycle import CycleResult, sync_all

log = logging.getLogger("costura.worker")

LEASE_SECONDS = 60.0
HEARTBEAT_SECONDS = 15.0
POLL_SECONDS = 2.0
PURGE_INTERVAL_SECONDS = 3600.0
DELIVERY_INTERVAL_SECONDS = 60.0
HISTORY_INTERVAL_SECONDS = 15 * 60.0
NO_ORGANIZATION = "scheduler run has no organization"


def worker_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _queued_claim(only_ids: Sequence[int] | None, exclude_orgs: set[int] | None):
    statement = select(SchedulerRun).where(
        SchedulerRun.status == "queued",
        SchedulerRun.attempt_count < SchedulerRun.max_attempts,
    )
    if only_ids is not None:
        statement = statement.where(SchedulerRun.id.in_(list(only_ids)))
    if exclude_orgs:
        statement = statement.where(
            or_(
                SchedulerRun.organization_id.is_(None),
                SchedulerRun.organization_id.not_in(exclude_orgs),
            )
        )
    return statement


def claim_next(
    owner: str,
    *,
    only_ids: Sequence[int] | None = None,
    exclude_orgs: set[int] | None = None,
) -> tuple[int, int | None] | None:
    """Claim the next queued row, after requeuing or failing expired leases.

    Returns `(run id, organization id)`, or None when nothing is claimable. `only_ids`
    limits the claim to one drain's rows; `exclude_orgs` skips organizations whose
    advisory lock was busy earlier in this pass.
    """
    if only_ids is not None and len(only_ids) == 0:
        return None
    now = datetime.now(UTC)
    with SessionLocal() as session:
        recover_abandoned_runs(session, commit=False)
        session.flush()
        statement = (
            _queued_claim(only_ids, exclude_orgs)
            .order_by(SchedulerRun.priority, SchedulerRun.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        run = session.scalar(statement)
        if run is None:
            session.commit()
            return None
        if run.status == "queued":
            run.started_at = now
        run.status = "running"
        run.attempt_count += 1
        run.lease_owner = owner
        run.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        run.heartbeat_at = now
        run.error = None
        claimed = (run.id, run.organization_id)
        log.info(
            "claimed scheduler run %s organization=%s provider=%s attempt=%s/%s",
            run.id,
            run.organization_id,
            run.provider,
            run.attempt_count,
            run.max_attempts,
        )
        session.commit()
        return claimed


def load_for_sync(session: Session, run_id: int) -> SchedulerRun:
    """Load a claimed run without its lease columns, so later commits cannot overwrite a
    heartbeat written on another connection."""
    run = session.scalar(
        select(SchedulerRun)
        .where(SchedulerRun.id == run_id)
        .options(
            defer(SchedulerRun.lease_owner),
            defer(SchedulerRun.lease_expires_at),
            defer(SchedulerRun.heartbeat_at),
        )
    )
    if run is None:
        raise RuntimeError(f"scheduler run {run_id} disappeared")
    return run


def _renew_lease(run_id: int, owner: str) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as session:
        session.execute(
            update(SchedulerRun)
            .where(
                SchedulerRun.id == run_id,
                SchedulerRun.lease_owner == owner,
                SchedulerRun.status == "running",
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            )
        )
        session.commit()


def _heartbeat(
    run_id: int, owner: str, stop: threading.Event, *, deadline_seconds: float | None = None
) -> None:
    """Renew the lease until the cycle ends or runs past `deadline_seconds` (default
    `STALL_SECONDS`); a stuck cycle then lets the lease expire so recovery can requeue it."""
    limit = STALL_SECONDS if deadline_seconds is None else deadline_seconds
    started = time.monotonic()
    while not stop.wait(HEARTBEAT_SECONDS):
        if time.monotonic() - started >= limit:
            log.error("scheduler run %s passed its deadline; the lease is left to expire", run_id)
            return
        try:
            _renew_lease(run_id, owner)
        except Exception:
            log.exception("heartbeat failed for scheduler run %s", run_id)


def _clear_lease(run_id: int, owner: str) -> None:
    with SessionLocal() as session:
        session.execute(
            update(SchedulerRun)
            .where(SchedulerRun.id == run_id, SchedulerRun.lease_owner == owner)
            .values(lease_owner=None, lease_expires_at=None, heartbeat_at=None)
        )
        session.commit()


def _release_claim(run_id: int, owner: str) -> None:
    """Put a claimed row back to queued when this process did not start its cycle."""
    with SessionLocal() as session:
        run = session.scalar(
            select(SchedulerRun).where(SchedulerRun.id == run_id).with_for_update()
        )
        if run is None or run.lease_owner != owner or run.status != "running":
            session.rollback()
            return
        run.attempt_count = max(0, run.attempt_count - 1)
        run.status = "queued"
        run.lease_owner = None
        run.lease_expires_at = None
        run.heartbeat_at = None
        session.commit()


def _sync_claimed(
    run_id: int,
    owner: str,
    *,
    factory: credentials.ClientFactory | None,
    sleep: Callable[[float], None],
) -> CycleResult:
    stop = threading.Event()
    beater = threading.Thread(
        target=_heartbeat,
        args=(run_id, owner, stop),
        name=f"sync-lease-{run_id}",
        daemon=True,
    )
    beater.start()
    try:
        settings = get_settings()
        with SessionLocal() as session:
            run = load_for_sync(session, run_id)
            if run.organization_id is None:
                run.status = "failed"
                run.error = NO_ORGANIZATION
                run.finished_at = datetime.now(UTC)
                session.commit()
                return CycleResult(
                    run_id=run.id,
                    organization_id=0,
                    provider=run.provider,
                    status="failed",
                    error=run.error,
                )
            result = sync_all(
                session,
                settings,
                run.organization_id,
                provider=run.provider,
                trigger=run.trigger,
                factory=factory,
                sleep=sleep,
                run=run,
            )
            log.info("scheduler run %s %s", result.run_id, result.status)
            return result
    finally:
        stop.set()
        beater.join(timeout=5)
        _clear_lease(run_id, owner)


def _execute_claimed(
    run_id: int,
    organization_id: int | None,
    owner: str,
    *,
    factory: credentials.ClientFactory | None,
    sleep: Callable[[float], None],
) -> CycleResult | None:
    if organization_id is None:
        return _sync_claimed(run_id, owner, factory=factory, sleep=sleep)
    with lock_connection(get_engine()) as lock:
        if not try_organization_lock(lock, organization_id):
            log.info(
                "organization %s lock busy; leaving scheduler run %s queued",
                organization_id,
                run_id,
            )
            _release_claim(run_id, owner)
            return None
        try:
            return _sync_claimed(run_id, owner, factory=factory, sleep=sleep)
        finally:
            unlock_organization(lock, organization_id)


def drain(
    *,
    factory: credentials.ClientFactory | None = None,
    sleep: Callable[[float], None] = time.sleep,
    only_ids: Sequence[int] | None = None,
    owner: str | None = None,
) -> list[CycleResult]:
    """Claim and run every currently available row, skipping organizations whose lock is held.

    `only_ids` drains those rows and no others (the daily `--once` path). An empty result
    means nothing was claimable or every remaining row's organization lock was busy; those
    rows stay queued.
    """
    owner = owner or worker_owner()
    results: list[CycleResult] = []
    excluded: set[int] = set()
    while True:
        claimed = claim_next(owner, only_ids=only_ids, exclude_orgs=excluded)
        if claimed is None:
            return results
        run_id, organization_id = claimed
        result = _execute_claimed(run_id, organization_id, owner, factory=factory, sleep=sleep)
        if result is None:
            if organization_id is not None:
                excluded.add(organization_id)
            continue
        results.append(result)


def maintain(last_purge: float, *, now: float | None = None) -> float:
    """Run retention when `PURGE_INTERVAL_SECONDS` has passed. A failure is logged and
    the clock still advances so the next poll does not retry immediately."""
    current = time.monotonic() if now is None else now
    if current - last_purge < PURGE_INTERVAL_SECONDS:
        return last_purge
    try:
        purge_and_log()
    except Exception:
        log.exception("retention purge failed")
    return current


def deliver_due(last_delivery: float, *, now: float | None = None) -> float:
    """Post due webhook deliveries when `DELIVERY_INTERVAL_SECONDS` has passed. A failure is
    logged and the clock still advances, as for retention."""
    current = time.monotonic() if now is None else now
    if current - last_delivery < DELIVERY_INTERVAL_SECONDS:
        return last_delivery
    try:
        from costura.delivery import deliver_all

        sent = deliver_all(SessionLocal, get_settings())
        if sent:
            log.info("webhook deliveries sent=%s", sent)
    except Exception:
        log.exception("webhook delivery pass failed")
    return current


def record_history_due(last_history: float, *, now: float | None = None) -> float:
    """Open and close signal history rows when `HISTORY_INTERVAL_SECONDS` has passed. A
    failure is logged and the clock still advances, as for delivery."""
    current = time.monotonic() if now is None else now
    if current - last_history < HISTORY_INTERVAL_SECONDS:
        return last_history
    try:
        from costura.signal_history import record_all

        changed = record_all(SessionLocal)
        if changed:
            log.info("signal history changed=%s", changed)
    except Exception:
        log.exception("signal history pass failed")
    return current


PULSE_SECONDS = 15
STALL_SECONDS = 3600
STOP_GRACE_SECONDS = 60


def _pulse() -> None:
    try:
        from costura.ops.heartbeat import beat

        beat("worker")
    except Exception:
        log.exception("worker heartbeat failed")


def _terminate_stalled() -> None:
    """Ask the main thread to stop (the cycle requeues its row), then exit hard if a blocking
    call never returns. Compose restarts the container either way."""
    os.kill(os.getpid(), signal.SIGTERM)
    time.sleep(STOP_GRACE_SECONDS)
    os._exit(1)


def _pulse_until(
    stop: threading.Event,
    progress: list[float],
    *,
    stall_seconds: float | None = None,
    terminate: Callable[[], None] | None = None,
) -> None:
    """Beat while the loop has moved within `stall_seconds` (default `STALL_SECONDS`). A
    drain stuck longer stops the heartbeat and ends the process, so the restart policy
    brings up a fresh worker."""
    limit = STALL_SECONDS if stall_seconds is None else stall_seconds
    while not stop.wait(PULSE_SECONDS):
        if time.monotonic() - progress[0] < limit:
            _pulse()
            continue
        log.error("worker made no progress for %s seconds; stopping", int(limit))
        (terminate or _terminate_stalled)()
        return


def run_worker(
    *,
    once: bool = False,
    poll_seconds: float = POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    factory: credentials.ClientFactory | None = None,
) -> Iterator[list[CycleResult]]:
    """Poll until stopped. `once` drains the claimable rows and returns. The heartbeat row is
    written every `PULSE_SECONDS` from a thread, so a long sync does not age it past the
    container healthcheck; a pass that runs longer than `STALL_SECONDS` stops the process."""
    last_purge = time.monotonic()
    last_delivery = last_purge - DELIVERY_INTERVAL_SECONDS
    last_history = last_purge - HISTORY_INTERVAL_SECONDS
    stop = threading.Event()
    progress = [time.monotonic()]
    _pulse()
    threading.Thread(
        target=_pulse_until, args=(stop, progress), name="worker-heartbeat", daemon=True
    ).start()
    try:
        while True:
            progress[0] = time.monotonic()
            yield drain(factory=factory, sleep=sleep)
            if once:
                return
            last_purge = maintain(last_purge)
            last_delivery = deliver_due(last_delivery)
            last_history = record_history_due(last_history)
            progress[0] = time.monotonic()
            sleep(poll_seconds)
    finally:
        stop.set()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="costura.ops.worker", description=__doc__)
    parser.add_argument("--once", action="store_true", help="drain claimable runs, then exit")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=POLL_SECONDS,
        help="sleep between empty passes (default %(default)s)",
    )
    args = parser.parse_args(argv)

    def operation() -> int:

        from costura.config import get_settings, require_production_runtime
        from costura.scheduler_lock import waiting_runs
        from costura.secrets import SecretKeyMissing

        settings = get_settings()
        require_production_runtime(settings)
        if settings.costura_secret_key is None:
            raise OperationError(str(SecretKeyMissing()))
        failed = False
        for results in run_worker(once=args.once, poll_seconds=args.poll_seconds):
            with SessionLocal() as session:
                slugs = {row.id: row.slug for row in session.query(Organization).all()}
            failed = _report_cycles(results, slugs, print_steps=args.once) or failed
        if args.once:
            with SessionLocal() as session:
                remaining, locked = waiting_runs(session)
            if locked:
                print(f"{locked} queued runs wait for an organization another worker holds")
            if remaining > locked:
                print(f"{remaining - locked} eligible runs still queued")
                return 1
        return 1 if args.once and failed else 0

    return run(operation)


if __name__ == "__main__":
    sys.exit(main())
