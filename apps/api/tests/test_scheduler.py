"""Scheduler: sync_all step counts, failure handling, skipped organizations, lock, timing."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from costura import credentials, scheduler, scheduler_lock, secrets, sync_cycle
from costura.config import get_settings
from costura.db import SessionLocal
from costura.models.credential import ProviderCredential
from costura.models.scheduler import SchedulerRun
from costura.models.sync import ProviderSyncRun
from costura.ops.worker import drain
from costura.orgs import create_org
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.openai.client import OpenAIAdminClient
from costura.providers.openrouter.client import OpenRouterManagementClient
from costura.providers.registry import ANTHROPIC_SPEC, OPENAI_SPEC, OPENROUTER_SPEC
from tests.conftest import (
    ORG_ID,
    account_of,
    anthropic_fixture_handler,
    openai_fixture_handler,
    openrouter_fixture_handler,
)

MONTHS = ["2026-08", "2026-07"]
NO_SLEEP = lambda _: None  # noqa: E731


def factory(key: str) -> AnthropicAdminClient:
    return AnthropicAdminClient(
        admin_key=key, transport=httpx.MockTransport(anthropic_fixture_handler), sleep=NO_SLEEP
    )


def openrouter_factory(key: str) -> OpenRouterManagementClient:
    return OpenRouterManagementClient(
        management_key=key,
        transport=httpx.MockTransport(openrouter_fixture_handler),
        sleep=NO_SLEEP,
    )


def openai_factory(key: str) -> OpenAIAdminClient:
    return OpenAIAdminClient(
        admin_key=key, transport=httpx.MockTransport(openai_fixture_handler), sleep=NO_SLEEP
    )


@pytest.fixture
def secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(secrets.generate_key()))
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", None)


@pytest.fixture
def stored_key(db_session: Session, org_id: int, secret_key: None) -> None:
    credentials.set_credential(
        db_session, get_settings(), org_id, "anthropic", "sk-ant-admin01-test", factory=factory
    )
    db_session.commit()


def test_person_budgets_wait_for_the_organizations_last_pending_cycle(
    db_session: Session, org_id: int, stored_key: None
) -> None:
    db_session.add(
        SchedulerRun(
            organization_id=org_id,
            provider="openai",
            trigger="scheduler",
            status="queued",
            steps=[],
        )
    )
    db_session.commit()

    result = sync_cycle.sync_all(
        db_session,
        get_settings(),
        org_id,
        provider="anthropic",
        months=MONTHS,
        factory=factory,
        sleep=NO_SLEEP,
    )

    person = [s for s in result.steps if s.step == "person_budgets"]
    assert result.status == "succeeded"
    assert [(s.status, s.detail) for s in person] == [
        ("skipped", sync_cycle.PERSON_BUDGETS_DEFERRED)
    ] * len(MONTHS)


def test_months_to_sync_is_current_then_previous() -> None:
    assert sync_cycle.months_to_sync(date(2026, 9, 14)) == ["2026-09", "2026-08"]
    assert sync_cycle.months_to_sync(date(2026, 1, 3)) == ["2026-01", "2025-12"]
    assert sync_cycle.months_to_sync(date(2026, 2, 3), 4) == [
        "2026-02",
        "2026-01",
        "2025-12",
        "2025-11",
    ]


def test_sync_all_runs_every_step_and_records_the_cycle(
    db_session: Session, org_id: int, stored_key: None
) -> None:
    result = sync_cycle.sync_all(
        db_session,
        get_settings(),
        org_id,
        provider="anthropic",
        months=MONTHS,
        factory=factory,
        sleep=NO_SLEEP,
    )

    assert result.status == "succeeded"
    # Financial plans run once after the current month's standing budgets.
    assert [(s.step, s.month) for s in result.steps] == [
        ("inventory", None),
        ("cost", "2026-08"),
        ("total", "2026-08"),
        ("usage", "2026-08"),
        ("cost", "2026-07"),
        ("total", "2026-07"),
        ("usage", "2026-07"),
        ("allocate", "2026-08"),
        ("detect", "2026-08"),
        ("project", "2026-08"),
        ("budgets", "2026-08"),
        ("person_budgets", "2026-08"),
        ("allocate", "2026-07"),
        ("detect", "2026-07"),
        ("project", "2026-07"),
        ("budgets", "2026-07"),
        ("person_budgets", "2026-07"),
    ]
    assert all(s.status == "ok" and s.attempts == 1 for s in result.steps)
    # Inventory syncs four listings in one step; every other step records one run.
    sync_runs = db_session.scalar(select(func.count()).select_from(ProviderSyncRun))
    assert sync_runs == 6 + 4 + 10

    row = db_session.get(SchedulerRun, result.run_id)
    assert row is not None
    assert row.status == "succeeded"
    assert row.trigger == "manual"
    assert row.finished_at is not None
    assert [s["step"] for s in row.steps][:4] == ["inventory", "cost", "total", "usage"]


def test_sync_all_continues_after_a_failing_step_and_retries_it(
    db_session: Session, org_id: int, stored_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def failing_usage(*_args: object, **_kwargs: object) -> None:
        calls.append("usage")
        raise RuntimeError("provider changed the payload")

    spec = replace(
        ANTHROPIC_SPEC,
        sync_steps=tuple(
            (name, failing_usage if name == "usage" else fn)
            for name, fn in ANTHROPIC_SPEC.sync_steps
        ),
    )
    monkeypatch.setattr(sync_cycle, "get_spec", lambda _provider: spec)
    slept: list[float] = []

    result = sync_cycle.sync_all(
        db_session,
        get_settings(),
        org_id,
        provider="anthropic",
        months=["2026-08"],
        factory=factory,
        sleep=slept.append,
    )

    assert result.status == "failed"
    usage = next(s for s in result.steps if s.step == "usage")
    assert usage.status == "failed"
    assert usage.attempts == sync_cycle.STEP_ATTEMPTS
    assert "provider changed the payload" in (usage.detail or "")
    assert len(calls) == sync_cycle.STEP_ATTEMPTS
    assert slept == [5.0, 30.0]
    # Independent report steps still ran; the dependent chain is deterministically skipped.
    assert [s.step for s in result.steps if s.status == "ok"] == [
        "inventory",
        "cost",
        "total",
    ]
    skipped = [s for s in result.steps if s.status == "skipped"]
    assert [(s.step, s.attempts, s.detail) for s in skipped] == [
        ("allocate", 0, "prerequisite not satisfied: usage=failed"),
        ("detect", 0, "prerequisite not satisfied: allocate=skipped"),
        ("project", 0, "prerequisite not satisfied: allocate=skipped"),
        ("budgets", 0, "prerequisite not satisfied: project=skipped"),
        ("person_budgets", 0, "prerequisite not satisfied: budgets=skipped"),
    ]
    assert db_session.get(SchedulerRun, result.run_id).status == "failed"


def test_sync_all_isolates_dependency_failures_by_month(
    db_session: Session, org_id: int, stored_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def usage_by_month(
        session: Session,
        organization_id: int,
        client: object,
        start: datetime,
        end: datetime,
    ) -> object:
        if start.month == 8:
            raise RuntimeError("August usage unavailable")
        return dict(ANTHROPIC_SPEC.sync_steps)["usage"](
            session, organization_id, client, start, end
        )

    spec = replace(
        ANTHROPIC_SPEC,
        sync_steps=tuple(
            (name, usage_by_month if name == "usage" else fn)
            for name, fn in ANTHROPIC_SPEC.sync_steps
        ),
    )
    monkeypatch.setattr(sync_cycle, "get_spec", lambda _provider: spec)

    result = sync_cycle.sync_all(
        db_session,
        get_settings(),
        org_id,
        provider="anthropic",
        months=MONTHS,
        factory=factory,
        sleep=NO_SLEEP,
    )

    august = [step for step in result.steps if step.month == "2026-08"]
    july = [step for step in result.steps if step.month == "2026-07"]
    assert next(step for step in august if step.step == "allocate").status == "skipped"
    assert all(step.status == "ok" for step in july)


def test_openrouter_total_and_inventory_do_not_block_combined_cost_allocation(
    db_session: Session,
    org_id: int,
    secret_key: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials.set_credential(
        db_session,
        get_settings(),
        org_id,
        "openrouter",
        "sk-or-v1-test",
        factory=openrouter_factory,
    )

    def failing_total(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("control total unavailable")

    spec = replace(
        OPENROUTER_SPEC,
        sync_steps=tuple(
            (name, failing_total if name == "total" else fn)
            for name, fn in OPENROUTER_SPEC.sync_steps
        ),
    )
    monkeypatch.setattr(sync_cycle, "get_spec", lambda _provider: spec)

    result = sync_cycle.sync_all(
        db_session,
        get_settings(),
        org_id,
        provider="openrouter",
        months=["2026-08"],
        factory=openrouter_factory,
        sleep=NO_SLEEP,
    )

    statuses = {step.step: step.status for step in result.steps}
    assert statuses == {
        "inventory": "ok",
        "cost": "ok",
        "total": "failed",
        "allocate": "ok",
        "detect": "ok",
        "project": "ok",
        "budgets": "ok",
        "person_budgets": "ok",
    }


def test_openai_allocation_waits_for_cost_and_usage_but_not_for_the_key_totals(
    db_session: Session,
    org_id: int,
    secret_key: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`allocation_inputs` on the spec, not a provider name in the scheduler, decides which
    report steps gate `allocate`: OpenAI needs cost and usage; `keys` is evidence only."""
    credentials.set_credential(
        db_session, get_settings(), org_id, "openai", "sk-admin-test", factory=openai_factory
    )

    def failing(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("report unavailable")

    def spec_failing(step_name: str):
        return replace(
            OPENAI_SPEC,
            sync_steps=tuple(
                (name, failing if name == step_name else fn) for name, fn in OPENAI_SPEC.sync_steps
            ),
        )

    monkeypatch.setattr(sync_cycle, "get_spec", lambda _provider: spec_failing("keys"))
    result = sync_cycle.sync_all(
        db_session,
        get_settings(),
        org_id,
        provider="openai",
        months=["2026-08"],
        factory=openai_factory,
        sleep=NO_SLEEP,
    )
    statuses = {step.step: step.status for step in result.steps}
    assert [s.step for s in result.steps][:5] == ["inventory", "cost", "total", "keys", "usage"]
    assert statuses["keys"] == "failed" and statuses["allocate"] == "ok"

    monkeypatch.setattr(sync_cycle, "get_spec", lambda _provider: spec_failing("usage"))
    result = sync_cycle.sync_all(
        db_session,
        get_settings(),
        org_id,
        provider="openai",
        months=["2026-08"],
        factory=openai_factory,
        sleep=NO_SLEEP,
    )
    statuses = {step.step: step.status for step in result.steps}
    assert statuses["usage"] == "failed" and statuses["allocate"] == "skipped"


def test_sync_all_persists_steps_after_each_one(
    db_session: Session, org_id: int, stored_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poller on another session sees the steps finished so far while the cycle runs."""
    seen: list[list[tuple[str, str | None, str]]] = []

    def observing_usage(*_args: object, **_kwargs: object) -> None:
        with SessionLocal() as poller:
            row = poller.scalar(select(SchedulerRun).order_by(SchedulerRun.id.desc()))
            assert row is not None and row.status == "running"
            seen.append([(s["step"], s["month"], s["status"]) for s in row.steps])

    spec = replace(
        ANTHROPIC_SPEC,
        sync_steps=tuple(
            (name, observing_usage if name == "usage" else fn)
            for name, fn in ANTHROPIC_SPEC.sync_steps
        ),
    )
    monkeypatch.setattr(sync_cycle, "get_spec", lambda _provider: spec)

    result = sync_cycle.sync_all(
        db_session,
        get_settings(),
        org_id,
        provider="anthropic",
        months=MONTHS,
        factory=factory,
        sleep=NO_SLEEP,
    )

    assert result.status == "succeeded"
    assert seen == [
        [("inventory", None, "ok"), ("cost", "2026-08", "ok"), ("total", "2026-08", "ok")],
        [
            ("inventory", None, "ok"),
            ("cost", "2026-08", "ok"),
            ("total", "2026-08", "ok"),
            ("usage", "2026-08", "ok"),
            ("cost", "2026-07", "ok"),
            ("total", "2026-07", "ok"),
        ],
    ]
    assert len(db_session.get(SchedulerRun, result.run_id).steps) == len(result.steps)


def test_sync_all_reuses_a_run_created_ahead(
    db_session: Session, org_id: int, stored_key: None
) -> None:
    run = SchedulerRun(organization_id=org_id, provider="anthropic", trigger="connect", steps=[])
    db_session.add(run)
    db_session.commit()

    result = sync_cycle.sync_all(
        db_session,
        get_settings(),
        org_id,
        provider="anthropic",
        months=["2026-08"],
        factory=factory,
        sleep=NO_SLEEP,
        run=run,
    )

    assert result.run_id == run.id and result.status == "succeeded"
    assert db_session.scalar(select(func.count()).select_from(SchedulerRun)) == 1
    assert run.status == "succeeded" and run.trigger == "connect"
    assert run.finished_at is not None and len(run.steps) == len(result.steps)


def test_drain_runs_a_queued_row_in_its_own_session_and_releases_the_lock(
    db_session: Session, org_id: int, stored_key: None
) -> None:
    run = SchedulerRun(organization_id=org_id, provider="anthropic", trigger="connect", steps=[])
    db_session.add(run)
    db_session.commit()
    assert run.status == "queued"

    [result] = drain(only_ids=[run.id], factory=factory, sleep=NO_SLEEP)

    assert result.run_id == run.id and result.status == "succeeded"
    db_session.refresh(run)
    assert run.status == "succeeded" and run.trigger == "connect"
    assert [s["step"] for s in run.steps][:2] == ["inventory", "cost"]
    # The organization lock is released after the cycle.
    assert scheduler_lock.try_organization_lock(db_session, org_id)
    scheduler_lock.unlock_organization(db_session, org_id)


def test_enqueued_run_transitions_to_running_only_after_lock_acquisition(
    db_session: Session,
    org_id: int,
    stored_key: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    [run] = scheduler.enqueue_runs(db_session, org_id, ["anthropic"], trigger="api")
    db_session.commit()
    assert run.status == "queued"
    observed: list[str] = []
    original_cost = dict(ANTHROPIC_SPEC.sync_steps)["cost"]

    def observing_cost(*args: Any, **kwargs: Any) -> Any:
        with SessionLocal() as poller:
            observed.append(poller.get(SchedulerRun, run.id).status)
        return original_cost(*args, **kwargs)

    spec = replace(
        ANTHROPIC_SPEC,
        sync_steps=tuple(
            (name, observing_cost if name == "cost" else fn)
            for name, fn in ANTHROPIC_SPEC.sync_steps
        ),
    )
    monkeypatch.setattr(sync_cycle, "get_spec", lambda _provider: spec)

    [result] = drain(only_ids=[run.id], factory=factory, sleep=NO_SLEEP)

    assert observed == ["running", "running"]
    assert result.status == "succeeded"
    db_session.refresh(run)
    assert run.status == "succeeded" and run.finished_at is not None


def test_organization_lock_leaves_the_run_queued(
    db_session: Session, org_id: int, stored_key: None
) -> None:
    [run] = scheduler.enqueue_runs(db_session, org_id, ["anthropic"], trigger="api")
    db_session.commit()

    with SessionLocal() as holder:
        assert scheduler_lock.try_organization_lock(holder, org_id)
        try:
            assert drain(only_ids=[run.id], factory=factory, sleep=NO_SLEEP) == []
        finally:
            scheduler_lock.unlock_organization(holder, org_id)

    db_session.refresh(run)
    assert run.status == "queued" and run.attempt_count == 0 and run.lease_owner is None
    assert db_session.scalar(select(func.count()).select_from(ProviderSyncRun)) == 0

    [result] = drain(only_ids=[run.id], factory=factory, sleep=NO_SLEEP)
    assert result.status == "succeeded"
    db_session.refresh(run)
    assert run.status == "succeeded" and run.lease_owner is None


def test_expired_lease_is_requeued_until_attempts_are_spent(
    db_session: Session, org_id: int
) -> None:
    future = datetime.now(UTC) + timedelta(minutes=5)
    past = datetime.now(UTC) - timedelta(minutes=5)
    live = SchedulerRun(
        organization_id=org_id,
        provider="anthropic",
        trigger="api",
        status="running",
        attempt_count=1,
        max_attempts=3,
        lease_owner="live",
        lease_expires_at=future,
        steps=[],
    )
    expired = SchedulerRun(
        organization_id=org_id,
        provider="openrouter",
        trigger="api",
        status="running",
        attempt_count=1,
        max_attempts=3,
        lease_owner="dead",
        lease_expires_at=past,
        steps=[],
    )
    waiting = SchedulerRun(
        organization_id=org_id,
        provider="openai",
        trigger="api",
        status="queued",
        started_at=past,
        steps=[],
    )
    spent = SchedulerRun(
        organization_id=org_id,
        provider="cursor",
        trigger="api",
        status="running",
        attempt_count=3,
        max_attempts=3,
        lease_owner="dead",
        lease_expires_at=past,
        steps=[],
    )
    db_session.add_all([live, expired, waiting, spent])
    db_session.commit()

    assert scheduler.recover_abandoned_runs_if_unlocked(db_session, org_id) == 2
    db_session.refresh(live)
    db_session.refresh(expired)
    db_session.refresh(waiting)
    db_session.refresh(spent)
    assert live.status == "running" and live.lease_owner == "live"
    assert waiting.status == "queued"
    assert expired.status == "queued" and expired.lease_owner is None and expired.attempt_count == 1
    assert spent.status == "failed" and spent.error == scheduler_lock.LEASE_EXHAUSTED
    assert spent.finished_at is not None and spent.lease_owner is None


def test_interrupt_requeues_the_cycle_and_fails_the_provider_run(
    db_session: Session, org_id: int, stored_key: None
) -> None:
    def interrupting_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/cost_report"):
            raise KeyboardInterrupt
        return anthropic_fixture_handler(request)

    def interrupting_factory(key: str) -> AnthropicAdminClient:
        return AnthropicAdminClient(
            admin_key=key,
            transport=httpx.MockTransport(interrupting_handler),
            sleep=NO_SLEEP,
        )

    with pytest.raises(KeyboardInterrupt):
        sync_cycle.sync_all(
            db_session,
            get_settings(),
            org_id,
            provider="anthropic",
            months=["2026-08"],
            factory=interrupting_factory,
            sleep=NO_SLEEP,
        )

    cycle = db_session.scalar(select(SchedulerRun).order_by(SchedulerRun.id.desc()))
    provider_run = db_session.scalar(
        select(ProviderSyncRun)
        .where(ProviderSyncRun.endpoint == "cost_report")
        .order_by(ProviderSyncRun.id.desc())
    )
    assert cycle is not None and cycle.status == "queued" and cycle.finished_at is None
    assert cycle.error is None and cycle.lease_owner is None and cycle.steps == []
    assert provider_run is not None
    assert provider_run.status == "failed" and provider_run.finished_at is not None
    assert provider_run.error == "KeyboardInterrupt:"


def test_sync_all_skips_an_organization_without_credential(
    db_session: Session, secret_key: None
) -> None:
    other = create_org(db_session, "acme", "Acme")

    result = sync_cycle.sync_all(
        db_session,
        get_settings(),
        other.id,
        provider="anthropic",
        months=MONTHS,
        factory=factory,
        sleep=NO_SLEEP,
    )

    assert result.status == "skipped"
    assert result.steps == []
    assert "web settings page" in (result.error or "")
    row = db_session.get(SchedulerRun, result.run_id)
    assert row.status == "skipped" and "web settings page" in (row.error or "")
    assert db_session.scalar(select(func.count()).select_from(ProviderSyncRun)) == 0


def test_auth_failure_is_not_retried_and_marks_the_credential(
    db_session: Session, org_id: int, stored_key: None
) -> None:
    def revoked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})

    def revoked_factory(key: str) -> AnthropicAdminClient:
        return AnthropicAdminClient(
            admin_key=key, transport=httpx.MockTransport(revoked), sleep=NO_SLEEP
        )

    result = sync_cycle.sync_all(
        db_session,
        get_settings(),
        org_id,
        provider="anthropic",
        months=["2026-08"],
        factory=revoked_factory,
        sleep=NO_SLEEP,
    )

    assert result.status == "failed"
    cost = result.steps[0]
    # The stored detail names the status and the path, never the provider's body: it reaches
    # the settings page as `last_error`.
    assert cost.attempts == 1
    assert (
        cost.detail
        == "Anthropic answered HTTP 401 to /v1/organizations/workspaces (request id unknown)"
    )
    stored = db_session.scalar(select(ProviderCredential))
    assert stored.last_error == cost.detail
    assert "invalid x-api-key" not in (stored.last_error or "")


def test_target_organizations_adds_costura_org_when_env_key_is_set(
    db_session: Session, org_id: int, secret_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = create_org(db_session, "acme", "Acme")
    credentials.set_credential(
        db_session, get_settings(), other.id, "anthropic", "sk-ant-admin01-acme", factory=factory
    )

    assert scheduler.target_organizations(db_session, get_settings(), provider="anthropic") == [
        other.id
    ]

    monkeypatch.setattr(get_settings(), "anthropic_admin_key", SecretStr("sk-ant-admin01-env"))
    assert scheduler.target_organizations(db_session, get_settings(), provider="anthropic") == [
        other.id,
        org_id,
    ]


def test_run_cycle_leaves_the_run_queued_while_the_organization_lock_is_held(
    db_session: Session, org_id: int, stored_key: None
) -> None:
    with SessionLocal() as other_runner:
        assert scheduler_lock.try_organization_lock(other_runner, org_id)
        try:
            assert scheduler.run_cycle(db_session, get_settings(), factory=factory) == []
        finally:
            scheduler_lock.unlock_organization(other_runner, org_id)

    queued = db_session.scalar(select(SchedulerRun).where(SchedulerRun.status == "queued"))
    assert queued is not None and queued.organization_id == org_id

    results = scheduler.run_cycle(db_session, get_settings(), factory=factory, sleep=NO_SLEEP)
    assert [r.organization_id for r in results] == [org_id]
    assert [r.provider for r in results] == ["anthropic"]
    assert scheduler_lock.try_organization_lock(db_session, org_id)
    scheduler_lock.unlock_organization(db_session, org_id)


def test_due_at_start_and_next_run(db_session: Session, org_id: int, stored_key: None) -> None:
    assert scheduler.due_at_start(db_session, get_settings()) is True

    db_session.add(
        SchedulerRun(
            organization_id=org_id,
            provider="anthropic",
            provider_account_id=account_of(db_session, org_id, "anthropic"),
            trigger="scheduler",
            status="succeeded",
            steps=[],
            started_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    assert scheduler.due_at_start(db_session, get_settings()) is False

    now = datetime(2026, 9, 14, 5, 30, tzinfo=UTC)
    assert scheduler.next_run_at("06:00", now) == datetime(2026, 9, 14, 6, 0, tzinfo=UTC)
    assert scheduler.next_run_at("05:00", now) == datetime(2026, 9, 15, 5, 0, tzinfo=UTC)


def test_run_forever_once_yields_one_cycle(
    db_session: Session, org_id: int, stored_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        scheduler.credentials,
        "default_factory",
        lambda _settings, _provider, _external_id=None: factory,
    )

    cycles = list(scheduler.run_forever(SessionLocal, get_settings(), once=True, sleep=NO_SLEEP))

    assert len(cycles) == 1
    assert [c.status for c in cycles[0]] == ["succeeded"]
    assert cycles[0][0].organization_id == org_id


@pytest.mark.parametrize(
    "values",
    [{"status": "done", "trigger": "manual"}, {"status": "queued", "trigger": "cron"}],
    ids=["status", "trigger"],
)
def test_database_refuses_an_unknown_run_status_or_trigger(
    db_session: Session, values: dict[str, str]
) -> None:
    db_session.add(SchedulerRun(organization_id=ORG_ID, provider="anthropic", **values))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_new_connection_backfills_and_skips_months_beyond_the_provider_history(
    db_session: Session, org_id: int, stored_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dataclasses

    from costura.providers import registry

    limited = dataclasses.replace(registry.get_spec("anthropic"), history_days=40)
    monkeypatch.setattr("costura.sync_cycle.get_spec", lambda name: limited)
    monkeypatch.setattr(get_settings(), "costura_backfill_months", 3)
    result = sync_cycle.sync_all(
        db_session,
        get_settings(),
        org_id,
        provider="anthropic",
        trigger="connect",
        factory=factory,
        sleep=NO_SLEEP,
        today=date(2026, 8, 20),
    )

    cost = {s.month: s for s in result.steps if s.step == "cost"}
    assert list(cost) == ["2026-08", "2026-07", "2026-06"]
    assert cost["2026-06"].status == "skipped"
    assert "40-day history" in (cost["2026-06"].detail or "")
    assert {cost["2026-08"].status, cost["2026-07"].status} == {"ok"}
    assert result.status == "succeeded"
