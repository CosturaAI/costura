"""Automatic ingestion: daily enqueue, the API's queued rows and the targets they name.

`run_forever` is the daemon behind `just api::scheduler` (`costura.ops.scheduler`). Once a
day at `COSTURA_SCHEDULE_AT` (UTC) it enqueues one idempotent run per target account.
`just api::worker` claims and executes those rows. `--once` enqueues and then drains
through that same claim path so a local run does not need a second process. With
`COSTURA_DEMO_REFRESH` the long-running pass also rebuilds a stale sample organization.

API requests only persist queued rows (`enqueue_runs`). They do not run syncs. Interactive
triggers (connect, api, manual) use a higher priority than the daily pass. One active run
per account is allowed for those triggers.

One account's cycle (steps, retries, prerequisites, live `steps`) is `costura.sync_cycle`.
The per-organization advisory lock and expired-lease recovery are `costura.scheduler_lock`.
"""

import logging
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import credentials
from costura.config import Settings
from costura.demo import refresh_if_stale
from costura.models.credential import ProviderCredential
from costura.models.organization import Organization
from costura.models.scheduler import SchedulerRun
from costura.ops.worker import drain
from costura.providers.registry import get_spec, provider_names
from costura.scheduler_lock import ACTIVE_RUN_STATUSES, recover_abandoned_runs_if_unlocked
from costura.scheduler_queue import enqueue_runs
from costura.sync_cycle import CycleResult, Trigger

log = logging.getLogger("costura.scheduler")

# Lower numbers are claimed first. Interactive syncs jump ahead of the daily pass.
PRIORITY_INTERACTIVE = 10
PRIORITY_DAILY = 100


def accounts_with_credentials(session: Session, *, provider: str) -> list[tuple[int, int]]:
    return [
        (int(org_id), int(account_id))
        for org_id, account_id in session.execute(
            select(ProviderCredential.organization_id, ProviderCredential.account_id)
            .where(ProviderCredential.provider == provider)
            .order_by(ProviderCredential.organization_id, ProviderCredential.account_id)
        ).all()
    ]


def target_accounts(
    session: Session, settings: Settings, *, provider: str
) -> list[tuple[int, int]]:
    """`(organization_id, account_id)` for every account with a stored key, plus the
    environment fallback account of `COSTURA_ORG` when its process key applies."""
    pairs = accounts_with_credentials(session, provider=provider)
    if get_spec(provider).env_key(settings) is not None:
        default_id = session.scalar(
            select(Organization.id).where(Organization.slug == settings.costura_org)
        )
        if default_id is not None and all(org != default_id for org, _ in pairs):
            account = credentials.environment_account(session, settings, default_id, provider)
            session.commit()
            if account is not None:
                pairs.append((default_id, account.id))
    return pairs


def target_organizations(session: Session, settings: Settings, *, provider: str) -> list[int]:
    """Organizations with at least one target account of the provider, each once."""
    ids: list[int] = []
    for org_id, _ in target_accounts(session, settings, provider=provider):
        if org_id not in ids:
            ids.append(org_id)
    return ids


def next_run_at(at: str, now: datetime | None = None) -> datetime:
    """Next occurrence of `HH:MM` UTC strictly after `now`."""
    now = now or datetime.now(UTC)
    hour, minute = (int(part) for part in at.split(":"))
    candidate = datetime.combine(now.date(), dtime(hour, minute, tzinfo=UTC))
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _scheduled_pairs(
    session: Session,
    settings: Settings,
    provider: str,
    *,
    named_provider: str | None,
    org_ids: list[int] | None,
) -> list[tuple[int, int | None]]:
    pairs: list[tuple[int, int | None]] = list(
        target_accounts(session, settings, provider=provider)
    )
    if org_ids is None:
        return pairs
    # An explicit organization is enqueued only for providers it has a key for, unless a
    # single provider was named (then the cycle records the missing key).
    with_key = {org for org, _ in pairs}
    narrowed = [(org, acc) for org, acc in pairs if org in org_ids]
    for org_id in org_ids:
        if org_id not in with_key and (
            named_provider is not None or not _any_key(session, settings, org_id)
        ):
            narrowed.append((org_id, None))
    return narrowed


def enqueue_scheduled_runs(
    session: Session,
    settings: Settings,
    *,
    provider: str | None = None,
    providers: Sequence[str] | None = None,
    trigger: Trigger = "scheduler",
    org_ids: list[int] | None = None,
    on: date | None = None,
) -> list[SchedulerRun]:
    """Insert and commit today's idempotent rows for every target account. Does not execute
    them. The scheduler process is the transaction boundary here."""
    selected = (provider,) if provider else tuple(providers or provider_names())
    grouped: dict[int, dict[str, list[int | None]]] = {}
    for name in selected:
        for org_id, account_id in _scheduled_pairs(
            session, settings, name, named_provider=provider, org_ids=org_ids
        ):
            grouped.setdefault(org_id, {}).setdefault(name, []).append(account_id)
    runs: list[SchedulerRun] = []
    for org_id, by_provider in grouped.items():
        runs.extend(
            enqueue_runs(
                session,
                org_id,
                list(by_provider),
                trigger=trigger,
                settings=settings,
                account_ids=by_provider,
                on=on,
            )
        )
    session.commit()
    queued = sum(1 for run in runs if run.status == "queued")
    log.info("daily sync queue has %s queued run(s) of %s considered", queued, len(runs))
    return runs


def run_cycle(
    session: Session,
    settings: Settings,
    *,
    provider: str | None = None,
    providers: Sequence[str] | None = None,
    trigger: Trigger = "scheduler",
    org_ids: list[int] | None = None,
    factory: credentials.ClientFactory | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[CycleResult]:
    """Enqueue today's runs, then drain the ones that are still queued or running.

    Returns an empty list when every selected row is already terminal, or when each
    remaining organization's advisory lock is held (those rows stay queued). `provider`
    narrows to one provider; `providers` to a list; the default is every registered
    provider. `org_ids` applies to every selected provider.
    """
    runs = enqueue_scheduled_runs(
        session,
        settings,
        provider=provider,
        providers=providers,
        trigger=trigger,
        org_ids=org_ids,
    )
    active = [run.id for run in runs if run.status in ACTIVE_RUN_STATUSES]
    if not active:
        return []

    return drain(only_ids=active, factory=factory, sleep=sleep)


def _any_key(session: Session, settings: Settings, org_id: int) -> bool:
    return any(
        org_id in target_organizations(session, settings, provider=p) for p in provider_names()
    )


def due_at_start(session: Session, settings: Settings, provider: str | None = None) -> bool:
    """True when some (target organization, provider) has no successful cycle in the last 24
    hours."""
    if provider is None:
        return any(due_at_start(session, settings, name) for name in provider_names())
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    for org_id, account_id in target_accounts(session, settings, provider=provider):
        last = session.scalar(
            select(SchedulerRun.started_at)
            .where(
                SchedulerRun.organization_id == org_id,
                SchedulerRun.provider == provider,
                SchedulerRun.provider_account_id == account_id,
                SchedulerRun.status == "succeeded",
            )
            .order_by(SchedulerRun.id.desc())
            .limit(1)
        )
        if last is None or last < cutoff:
            return True
    return False


def run_forever(
    session_factory: Callable[[], Session],
    settings: Settings,
    *,
    at: str | None = None,
    once: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Iterator[list[CycleResult]]:
    """Daemon loop. The long-running form only enqueues. `once` enqueues and drains once,
    which is what `just api::scheduler --once` runs."""
    at = at or settings.costura_schedule_at
    if once:
        with session_factory() as session:
            yield run_cycle(session, settings, sleep=sleep)
        return
    with session_factory() as session:
        if due_at_start(session, settings):
            enqueue_scheduled_runs(session, settings)
            yield []
        refresh_demo_if_enabled(session, settings)
    while True:
        target = next_run_at(at, clock())
        wait = max(0.0, (target - clock()).total_seconds())
        log.info(
            "next scheduler pass at %s (in %.0f s)",
            target.isoformat(timespec="seconds"),
            wait,
        )
        sleep(wait)
        with session_factory() as session:
            enqueue_scheduled_runs(session, settings)
            refresh_demo_if_enabled(session, settings)
            yield []


def refresh_demo_if_enabled(session: Session, settings: Settings) -> bool:
    """Rebuild a stale sample organization when `COSTURA_DEMO_REFRESH` is on. A failure is
    logged and leaves the published sample as it was; the provider syncs are unaffected."""
    if not settings.costura_demo_refresh:
        return False

    try:
        return refresh_if_stale(session) is not None
    except Exception:
        session.rollback()
        log.exception("sample organization refresh failed; the published sample is unchanged")
        return False


__all__ = [
    "due_at_start",
    "enqueue_runs",
    "enqueue_scheduled_runs",
    "next_run_at",
    "recover_abandoned_runs_if_unlocked",
    "run_cycle",
    "run_forever",
    "target_accounts",
    "target_organizations",
]
