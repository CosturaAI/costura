"""Durable scheduler queue: claim, idempotency, lease recovery and the worker process."""

import threading
import time
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from costura import credentials, scheduler, scheduler_lock, secrets
from costura.config import get_settings
from costura.db import SessionLocal
from costura.models.scheduler import SchedulerRun
from costura.ops import worker
from costura.orgs import create_org
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.registry import ANTHROPIC_SPEC
from costura.scheduler_queue import SchedulerBusy
from costura.sync_cycle import sanitize_stored_error
from tests.conftest import ORG_ID, account_of, anthropic_fixture_handler

NO_SLEEP = lambda _: None  # noqa: E731


def factory(key: str) -> AnthropicAdminClient:
    return AnthropicAdminClient(
        admin_key=key, transport=httpx.MockTransport(anthropic_fixture_handler), sleep=NO_SLEEP
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


def test_stored_error_drops_a_provider_body_and_truncates() -> None:
    body = "x" * 800
    cleaned = sanitize_stored_error(f"status=400 path=/v1/costs body='{body}'")
    assert cleaned is not None
    assert "body=" not in cleaned
    assert cleaned.startswith("status=400")
    assert len(cleaned) <= 500
    assert sanitize_stored_error(None) is None
    assert sanitize_stored_error("   ") is None


def test_daily_enqueue_is_idempotent_for_one_utc_day(
    db_session: Session, org_id: int, stored_key: None
) -> None:
    day = date(2026, 10, 9)
    first = scheduler.enqueue_runs(db_session, org_id, ["anthropic"], trigger="scheduler", on=day)
    db_session.commit()
    second = scheduler.enqueue_runs(db_session, org_id, ["anthropic"], trigger="scheduler", on=day)
    db_session.commit()
    assert first[0].id == second[0].id
    assert first[0].priority == scheduler.PRIORITY_DAILY
    account = first[0].provider_account_id
    assert first[0].idempotency_key == f"{org_id}:anthropic:{account}:scheduler:{day.isoformat()}"

    later = scheduler.enqueue_runs(
        db_session, org_id, ["anthropic"], trigger="scheduler", on=date(2026, 10, 10)
    )
    db_session.commit()
    assert later[0].id != first[0].id
    with pytest.raises(SchedulerBusy, match="sync already queued"):
        scheduler.enqueue_runs(db_session, org_id, ["anthropic"], trigger="api")
    db_session.rollback()

    duplicate = SchedulerRun(
        organization_id=org_id,
        provider="anthropic",
        trigger="scheduler",
        status="queued",
        steps=[],
        idempotency_key=first[0].idempotency_key,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(SchedulerRun)) == 2


def test_claim_prefers_an_interactive_run_over_an_older_daily_run(
    db_session: Session, org_id: int
) -> None:
    other = create_org(db_session, "acme", "Acme")
    daily = SchedulerRun(
        organization_id=org_id,
        provider="anthropic",
        trigger="scheduler",
        status="queued",
        priority=scheduler.PRIORITY_DAILY,
        steps=[],
    )
    db_session.add(daily)
    db_session.commit()
    urgent = SchedulerRun(
        organization_id=other.id,
        provider="anthropic",
        trigger="api",
        status="queued",
        priority=scheduler.PRIORITY_INTERACTIVE,
        steps=[],
    )
    db_session.add(urgent)
    db_session.commit()
    assert daily.id < urgent.id

    first = worker.claim_next("worker-a")
    second = worker.claim_next("worker-b")
    assert first == (urgent.id, other.id)
    assert second == (daily.id, org_id)
    db_session.refresh(urgent)
    assert urgent.status == "running" and urgent.attempt_count == 1
    assert urgent.lease_owner == "worker-a" and urgent.lease_expires_at is not None


def test_drain_stamps_progress_at_each_claim(
    db_session: Session, org_id: int, stored_key: None
) -> None:
    scheduler.enqueue_runs(db_session, org_id, ["anthropic"], trigger="connect")
    db_session.commit()
    progress = [0.0]
    before = time.monotonic()

    [result] = worker.drain(factory=factory, sleep=NO_SLEEP, progress=progress)

    assert result.status == "succeeded"
    assert progress[0] >= before


def test_drain_runs_a_queued_row_and_clears_the_lease(
    db_session: Session, org_id: int, stored_key: None
) -> None:
    [run] = scheduler.enqueue_runs(db_session, org_id, ["anthropic"], trigger="connect")
    db_session.commit()
    assert run.priority == scheduler.PRIORITY_INTERACTIVE

    [result] = worker.drain(factory=factory, sleep=NO_SLEEP)

    assert result.status == "succeeded" and result.run_id == run.id
    db_session.refresh(run)
    assert run.status == "succeeded" and run.attempt_count == 1
    assert run.lease_owner is None and run.lease_expires_at is None and run.heartbeat_at is None
    assert run.finished_at is not None


def test_drain_reclaims_an_expired_lease(
    db_session: Session, org_id: int, stored_key: None
) -> None:
    run = SchedulerRun(
        organization_id=org_id,
        provider="anthropic",
        provider_account_id=account_of(db_session, org_id, "anthropic"),
        trigger="api",
        status="running",
        attempt_count=1,
        max_attempts=3,
        lease_owner="dead",
        lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
        steps=[],
    )
    db_session.add(run)
    db_session.commit()

    [result] = worker.drain(factory=factory, sleep=NO_SLEEP)

    assert result.status == "succeeded" and result.run_id == run.id
    db_session.refresh(run)
    assert run.attempt_count == 2 and run.status == "succeeded"
    assert run.lease_owner is None


def test_sync_commits_do_not_overwrite_a_renewed_lease(db_session: Session, org_id: int) -> None:
    run = SchedulerRun(
        organization_id=org_id, provider="anthropic", trigger="api", status="queued", steps=[]
    )
    db_session.add(run)
    db_session.commit()
    assert worker.claim_next("owner") == (run.id, org_id)

    extended = datetime.now(UTC) + timedelta(hours=2)
    with SessionLocal() as session:
        loaded = worker.load_for_sync(session, run.id)
        with SessionLocal() as other:
            row = other.get(SchedulerRun, run.id)
            assert row is not None
            row.lease_expires_at = extended
            row.heartbeat_at = extended
            other.commit()
        loaded.steps = [{"step": "inventory", "status": "ok"}]
        session.commit()

    with SessionLocal() as check:
        saved = check.get(SchedulerRun, run.id)
        assert saved is not None
        assert saved.steps == [{"step": "inventory", "status": "ok"}]
        assert saved.lease_expires_at is not None
        assert saved.lease_expires_at > datetime.now(UTC) + timedelta(hours=1)
        assert saved.heartbeat_at == saved.lease_expires_at


def test_another_organization_runs_while_one_holds_its_lock(
    db_session: Session, org_id: int, secret_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = create_org(db_session, "acme", "Acme")
    credentials.set_credential(
        db_session, get_settings(), org_id, "anthropic", "sk-ant-admin01-a", factory=factory
    )
    credentials.set_credential(
        db_session, get_settings(), other.id, "anthropic", "sk-ant-admin01-b", factory=factory
    )
    scheduler.enqueue_runs(db_session, org_id, ["anthropic"], trigger="api")
    db_session.commit()
    scheduler.enqueue_runs(db_session, other.id, ["anthropic"], trigger="api")
    db_session.commit()
    monkeypatch.setattr(worker, "HEARTBEAT_SECONDS", 0.05)

    started = threading.Event()
    release = threading.Event()
    original = ANTHROPIC_SPEC.run_inventory_sync

    def blocking(session: Session, target: object, client: object) -> object:
        if getattr(target, "org_id", None) == org_id:
            started.set()
            assert release.wait(10)
        return original(session, target, client)

    monkeypatch.setattr(
        "costura.sync_cycle.get_spec",
        lambda _provider: replace(ANTHROPIC_SPEC, run_inventory_sync=blocking),
    )
    finished: list[list] = []

    def run_blocked() -> None:
        finished.append(worker.drain(factory=factory, sleep=NO_SLEEP))

    thread = threading.Thread(target=run_blocked)
    thread.start()
    renewed = False
    others: list = []
    try:
        assert started.wait(10)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with SessionLocal() as session:
                row = session.scalar(
                    select(SchedulerRun).where(
                        SchedulerRun.organization_id == org_id,
                        SchedulerRun.status == "running",
                    )
                )
                if (
                    row is not None
                    and row.heartbeat_at is not None
                    and row.started_at is not None
                    and row.heartbeat_at > row.started_at
                ):
                    renewed = True
                    break
            time.sleep(0.02)
        others = worker.drain(factory=factory, sleep=NO_SLEEP)
    finally:
        release.set()
        thread.join(30)

    assert renewed
    assert [result.organization_id for result in others] == [other.id]
    assert others[0].status == "succeeded"
    assert len(finished) == 1
    assert [result.organization_id for result in finished[0]] == [org_id]
    assert finished[0][0].status == "succeeded"
    assert scheduler_lock.try_organization_lock(db_session, org_id)
    scheduler_lock.unlock_organization(db_session, org_id)
    assert scheduler_lock.try_organization_lock(db_session, other.id)
    scheduler_lock.unlock_organization(db_session, other.id)


def test_worker_once_requires_a_secret_key(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(get_settings(), "costura_secret_key", None)
    assert worker.main(["--once"]) == 1
    assert "COSTURA_SECRET_KEY is not set" in capsys.readouterr().err


def test_worker_once_exits_zero_when_nothing_is_queued(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(secrets.generate_key()))
    assert worker.main(["--once"]) == 0


def test_worker_once_exits_zero_when_another_worker_holds_the_organization(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A row left queued behind another process's lock is not a failure of this pass."""
    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(secrets.generate_key()))
    db_session.add(
        SchedulerRun(organization_id=ORG_ID, provider="anthropic", trigger="api", status="queued")
    )
    db_session.commit()
    from costura.db import get_engine

    with scheduler_lock.lock_connection(get_engine()) as holder:
        assert scheduler_lock.try_organization_lock(holder, ORG_ID)
        holder.commit()
        assert worker.main(["--once"]) == 0
        scheduler_lock.unlock_organization(holder, ORG_ID)
    assert "1 queued runs wait for an organization another worker holds" in capsys.readouterr().out


def test_lease_renewal_stops_at_the_cycle_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stuck cycle lets its lease expire so recovery can requeue the row."""
    renewed: list[int] = []
    monkeypatch.setattr(worker, "HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(worker, "_renew_lease", lambda run_id, _owner: renewed.append(run_id))
    stop = threading.Event()
    beater = threading.Thread(
        target=worker._heartbeat, args=(7, "owner", stop), kwargs={"deadline_seconds": 0.05}
    )
    beater.start()
    beater.join(timeout=2)
    stop.set()
    assert not beater.is_alive()
    assert 0 < len(renewed) < 10


def test_a_stalled_worker_stops_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """No progress past the stall limit ends the process instead of beating forever."""
    monkeypatch.setattr(worker, "PULSE_SECONDS", 0.01)
    monkeypatch.setattr(worker, "_pulse", lambda: None)
    stopped: list[bool] = []
    progress = [time.monotonic() - 10]
    worker._pulse_until(
        threading.Event(), progress, stall_seconds=5, terminate=lambda: stopped.append(True)
    )
    assert stopped == [True]
