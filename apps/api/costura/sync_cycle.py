"""One sync cycle for one provider account: inventory, the provider's report steps for each
month, then allocation, detection, projection and budgets, each gated on its inputs.

Every step is retried (`STEP_ATTEMPTS`, `RETRY_BACKOFF_SECONDS`) except on a refused key, and a
step whose prerequisite did not succeed is recorded as skipped. The cycle's `scheduler_runs`
row is rewritten after every step so a poller sees live progress."""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import credentials
from costura.config import Settings
from costura.models.budget import PERSON_BUDGET_PROVIDER
from costura.models.scheduler import SchedulerRun
from costura.ops import TerminationSignal
from costura.providers.http import (
    ProviderApiError,
    ProviderAuthError,
    public_message,
    sanitize_stored_error,
)
from costura.providers.registry import get_spec
from costura.providers.runs import Target
from costura.providers.spec import ProviderClient
from costura.scheduler_lock import ACTIVE_RUN_STATUSES
from costura.spend.allocate import run_allocation
from costura.spend.anomalies import run_detection
from costura.spend.anomaly_store import purge_expired
from costura.spend.budgets import evaluate_budgets
from costura.spend.projection import run_projection
from costura.spend.summary import previous_month
from costura.spend.window import Window

log = logging.getLogger("costura.sync")

STEP_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (5.0, 30.0)
INTERRUPTED_RUN = "sync interrupted before completion"
Trigger = Literal["scheduler", "manual", "api", "connect"]


def _stored_exception(exc: BaseException) -> str:
    if isinstance(exc, ProviderApiError):
        return sanitize_stored_error(exc.public) or INTERRUPTED_RUN
    if not str(exc):
        return INTERRUPTED_RUN
    return sanitize_stored_error(f"{type(exc).__name__}: {exc}") or INTERRUPTED_RUN


@dataclass
class StepResult:
    step: str
    month: str | None
    status: Literal["ok", "failed", "skipped"]
    attempts: int = 0
    detail: str | None = None
    duration_seconds: float = 0.0
    # The provider refused the key (401 or 403): the cycle records it on the credential.
    auth_failed: bool = False


@dataclass
class CycleResult:
    run_id: int
    organization_id: int
    provider: str
    status: Literal["succeeded", "failed", "skipped"]
    account_id: int | None = None
    steps: list[StepResult] = field(default_factory=list)
    error: str | None = None

    @property
    def failed_steps(self) -> list[StepResult]:
        return [s for s in self.steps if s.status == "failed"]


DAILY_MONTHS = 2


def months_to_sync(today: date | None = None, count: int = DAILY_MONTHS) -> list[str]:
    """Current month first, then the ones before it: late data lands in the last two, and a
    new connection reads further back so baselines exist on day one."""
    today = today or datetime.now(UTC).date()
    months = [f"{today.year}-{today.month:02d}"]
    while len(months) < count:
        months.append(previous_month(months[-1]))
    return months


def _attempt(
    name: str,
    month: str | None,
    fn: Callable[[], object],
    *,
    sleep: Callable[[float], None],
) -> StepResult:
    result = StepResult(step=name, month=month, status="failed")
    started = time.monotonic()
    for attempt in range(1, STEP_ATTEMPTS + 1):
        result.attempts = attempt
        try:
            fn()
        except ProviderAuthError as exc:
            # A bad key does not get better on retry; stop the step and let the cycle report it.
            # The stored detail reaches the settings page, so it is the public sentence.
            result.detail = public_message(exc)
            result.auth_failed = True
            break
        except Exception as exc:
            result.detail = public_message(exc)
            if attempt < STEP_ATTEMPTS:
                sleep(RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)])
        else:
            result.status = "ok"
            result.detail = None
            break
    result.duration_seconds = round(time.monotonic() - started, 3)
    return result


def _dependent_attempt(
    name: str,
    month: str,
    fn: Callable[[], object],
    prerequisites: Sequence[StepResult],
    *,
    sleep: Callable[[float], None],
) -> StepResult:
    blocked = [step for step in prerequisites if step.status != "ok"]
    if blocked:
        detail = ", ".join(f"{step.step}={step.status}" for step in blocked)
        return StepResult(
            step=name,
            month=month,
            status="skipped",
            attempts=0,
            detail=f"prerequisite not satisfied: {detail}",
        )
    return _attempt(name, month, fn, sleep=sleep)


def _start_run(session: Session, run: SchedulerRun) -> None:
    if run.status == "queued":
        run.status = "running"
        run.started_at = datetime.now(UTC)
        session.commit()
    elif run.status != "running":
        raise RuntimeError(f"scheduler run {run.id} is already {run.status}")


def sync_all(
    session: Session,
    settings: Settings,
    org_id: int,
    *,
    provider: str,
    account_id: int | None = None,
    trigger: Trigger = "manual",
    months: list[str] | None = None,
    factory: credentials.ClientFactory | None = None,
    sleep: Callable[[float], None] = time.sleep,
    run: SchedulerRun | None = None,
    client: ProviderClient | None = None,
    today: date | None = None,
) -> CycleResult:
    """Every step for one provider account. Never raises for a step failure; the cycle row and
    the returned result carry the outcome. Raises nothing for a missing credential either: the
    cycle is recorded as `skipped` with the reason. `account_id` names the account; without it
    (and without a queued `run` that names one) the provider's first connected account is
    used. `run` is a queued row a request created ahead of time so its id could be returned
    before lock acquisition; without it the cycle creates and immediately claims its own.

    `client` replaces the credential lookup with a ready provider client (the sample
    organization's synthetic one); `today` is the day detection, projection and budgets
    measure against, the current UTC day by default."""
    if account_id is None and run is not None:
        account_id = run.provider_account_id
    if account_id is None:
        account_id = default_account_id(session, settings, org_id, provider)
    run = _claim_run(session, run, org_id, provider, account_id, trigger)
    result = CycleResult(
        run_id=run.id,
        organization_id=org_id,
        provider=provider,
        status="failed",
        account_id=account_id,
    )

    def record(step: StepResult) -> None:
        result.steps.append(step)
        log.log(
            logging.WARNING if step.status == "failed" else logging.INFO,
            "sync step %s %s %s %s %.3fs run_id=%s",
            provider,
            step.step,
            step.month or "-",
            step.status,
            step.duration_seconds,
            run.id,
            extra={
                "run_id": run.id,
                "org_id": org_id,
                "provider": provider,
                "step": step.step,
                "month": step.month,
                "status": step.status,
                "duration_seconds": round(step.duration_seconds, 3),
            },
        )
        # A new list, not an in-place append: JSONB change detection compares by identity.
        run.steps = [asdict(s) for s in result.steps]
        session.commit()

    try:
        try:
            if account_id is None:
                raise credentials.NoCredential(provider)
            if client is None:
                client = credentials.get_client(
                    session, settings, org_id, provider, account_id, factory=factory
                )
        except (credentials.NoCredential, RuntimeError) as exc:
            result.status = "skipped"
            result.error = str(exc)
            _finish(session, run, result)
            return result

        cycle = _Cycle(
            session=session,
            target=Target(org_id=org_id, account_id=account_id),
            provider=provider,
            run_id=run.id,
            today=today,
            record=record,
            sleep=sleep,
        )
        with client:
            count = settings.costura_backfill_months if trigger == "connect" else DAILY_MONTHS
            by_month = cycle.reports(client, months or months_to_sync(today, count))
            for month, reports in by_month.items():
                cycle.derived(month, reports)
    except TerminationSignal, KeyboardInterrupt:
        session.rollback()
        _requeue(session, run)
        raise
    except BaseException as exc:
        session.rollback()
        result.status = "failed"
        result.error = _stored_exception(exc)
        _finish(session, run, result)
        raise

    auth_failures = [s for s in result.failed_steps if s.auth_failed]
    if auth_failures and account_id is not None:
        credentials.record_error(session, account_id, auth_failures[0].detail or "")
    result.status = "failed" if result.failed_steps else "succeeded"
    _finish(session, run, result)
    if run.organization_id is not None:
        purge_expired(session, run.organization_id, today=today)
    return result


def _requeue(session: Session, run: SchedulerRun) -> None:
    """An operator stop (SIGTERM, Ctrl-C) is not a failed import: the row goes back to the
    queue with the claim's attempt undone, and the next worker runs it again."""
    run.status = "queued"
    run.attempt_count = max(0, run.attempt_count - 1)
    run.error = None
    run.finished_at = None
    run.steps = []
    run.lease_owner = None
    run.lease_expires_at = None
    run.heartbeat_at = None
    session.commit()
    log.info("scheduler run %s requeued after a stop signal", run.id)


def _finish(session: Session, run: SchedulerRun, result: CycleResult) -> None:
    run.status = result.status
    run.error = sanitize_stored_error(result.error)
    run.steps = [asdict(step) for step in result.steps]
    run.finished_at = datetime.now(UTC)
    session.commit()


def _claim_run(
    session: Session,
    run: SchedulerRun | None,
    org_id: int,
    provider: str,
    account_id: int | None,
    trigger: Trigger,
) -> SchedulerRun:
    if run is None:
        run = SchedulerRun(
            organization_id=org_id,
            provider=provider,
            provider_account_id=account_id,
            trigger=trigger,
            status="queued",
            steps=[],
        )
        session.add(run)
        session.commit()
    elif run.provider_account_id is None and account_id is not None:
        run.provider_account_id = account_id
    _start_run(session, run)
    return run


@dataclass
class _Cycle:
    """The steps of one cycle, recorded on its run row as each finishes."""

    session: Session
    target: Target
    provider: str
    run_id: int
    today: date | None
    record: Callable[[StepResult], None]
    sleep: Callable[[float], None]

    def reports(
        self, client: ProviderClient, months: list[str]
    ) -> dict[str, dict[str, StepResult]]:
        """The provider reads. Inventory enriches labels but does not block any report or
        derived step."""
        spec = get_spec(self.provider)
        session, target = self.session, self.target
        self.record(
            _attempt(
                "inventory",
                None,
                lambda: spec.run_inventory_sync(session, target, client),
                sleep=self.sleep,
            )
        )
        by_month: dict[str, dict[str, StepResult]] = {month: {} for month in months}
        today = self.today or datetime.now(UTC).date()
        for month in months:
            window = Window.for_month(month)
            if spec.history_days is not None and window.last_day < today - timedelta(
                days=spec.history_days
            ):
                for name, _ in spec.sync_steps:
                    step = StepResult(
                        step=name,
                        month=month,
                        status="skipped",
                        detail=f"before the {spec.history_days}-day history the provider serves",
                    )
                    by_month[month][name] = step
                    self.record(step)
                continue
            for name, fn in spec.sync_steps:
                step = _attempt(
                    name,
                    month,
                    lambda fn=fn, w=window: fn(session, target, client, w.start, w.end),
                    sleep=self.sleep,
                )
                by_month[month][name] = step
                self.record(step)
        return by_month

    def derived(self, month: str, reports: dict[str, StepResult]) -> None:
        """Allocation, then detection and projection on it, then budgets on the projection."""
        session, org_id, provider = self.session, self.target.org_id, self.provider
        account_id, today = self.target.account_id, self.today
        window = Window.for_month(month)
        allocation = self._step(
            "allocate",
            month,
            lambda: run_allocation(session, org_id, provider, window, account_id=account_id),
            [reports[name] for name in get_spec(provider).allocation_inputs],
        )
        self._step(
            "detect",
            month,
            lambda: run_detection(
                session, org_id, provider, window, account_id=account_id, today=today
            ),
            [allocation],
        )
        projection = self._step(
            "project",
            month,
            lambda: run_projection(
                session, org_id, provider, window, account_id=account_id, today=today
            ),
            [allocation],
        )
        budget_step = self._step(
            "budgets",
            month,
            lambda: evaluate_budgets(session, org_id, provider, window, today=today),
            [projection],
        )
        if _other_cycles_pending(session, org_id, self.run_id):
            self.record(
                StepResult(
                    step="person_budgets",
                    month=month,
                    status="skipped",
                    attempts=0,
                    detail=PERSON_BUDGETS_DEFERRED,
                )
            )
            return
        self._step(
            "person_budgets",
            month,
            lambda: evaluate_budgets(session, org_id, PERSON_BUDGET_PROVIDER, window, today=today),
            [budget_step],
        )

    def _step(
        self,
        name: str,
        month: str,
        fn: Callable[[], object],
        prerequisites: Sequence[StepResult],
    ) -> StepResult:
        step = _dependent_attempt(name, month, fn, prerequisites, sleep=self.sleep)
        self.record(step)
        return step


PERSON_BUDGETS_DEFERRED = "another cycle of the organization is pending; the last one evaluates"


def _other_cycles_pending(session: Session, org_id: int, run_id: int) -> bool:
    """Person budgets read every provider, so one evaluation after the organization's last
    pending cycle replaces one per provider."""
    return (
        session.scalar(
            select(SchedulerRun.id)
            .where(
                SchedulerRun.organization_id == org_id,
                SchedulerRun.id != run_id,
                SchedulerRun.status.in_(ACTIVE_RUN_STATUSES),
            )
            .limit(1)
        )
        is not None
    )


def default_account_id(
    session: Session, settings: Settings, org_id: int, provider: str
) -> int | None:
    """The account a cycle without an explicit one runs for: the provider's first connected
    account (the environment fallback account when only the process key applies)."""
    credentials.environment_account(session, settings, org_id, provider)
    connected = credentials.connected_accounts(session, settings, org_id, provider)
    return connected[0].account_id if connected else None
