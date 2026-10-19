"""Retention of raw provider pages and finished runs (`costura.ops.purge`)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import ProviderReportPage, ProviderSyncRun, SchedulerRun, SpendCostLine
from costura.ops import purge as purge_mod
from costura.ops import worker
from tests.conftest import ORG_ID, account_of

NOW = datetime(2026, 10, 9, tzinfo=UTC)
OLD = NOW - timedelta(days=120)
RECENT = NOW - timedelta(days=2)


def _sync(
    session: Session, *, status: str, finished: datetime | None, endpoint: str
) -> ProviderSyncRun:
    run = ProviderSyncRun(
        organization_id=ORG_ID,
        provider="anthropic",
        endpoint=endpoint,
        window_start=OLD,
        window_end=OLD,
        status=status,
        started_at=OLD,
        finished_at=finished,
    )
    session.add(run)
    session.flush()
    return run


def _page(session: Session, run: ProviderSyncRun, fetched: datetime, index: int) -> None:
    session.add(
        ProviderReportPage(
            organization_id=ORG_ID,
            sync_run_id=run.id,
            provider="anthropic",
            endpoint=run.endpoint,
            page_index=index,
            request_params={},
            payload={"kept": True},
            fetched_at=fetched,
        )
    )


def _scheduler(session: Session, *, status: str, finished: datetime | None) -> SchedulerRun:
    row = SchedulerRun(
        organization_id=ORG_ID,
        provider="anthropic",
        trigger="scheduler",
        status=status,
        started_at=OLD,
        finished_at=finished,
    )
    session.add(row)
    return row


def _count(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def test_zero_retention_keeps_every_row(db_session: Session) -> None:
    run = _sync(db_session, status="succeeded", finished=OLD, endpoint="old")
    _page(db_session, run, OLD, 0)
    _scheduler(db_session, status="failed", finished=OLD)
    db_session.commit()

    counts = purge_mod.purge(db_session, now=NOW, page_days=0, run_days=0)

    assert counts == purge_mod.PurgeCounts(0, 0, 0, 0)
    assert _count(db_session, ProviderReportPage) == 1
    assert _count(db_session, ProviderSyncRun) == 1
    assert _count(db_session, SchedulerRun) == 1


def test_purge_drops_old_pages_and_unreferenced_runs_only(db_session: Session) -> None:
    account_id = account_of(db_session, ORG_ID, "anthropic")
    referenced = _sync(db_session, status="succeeded", finished=OLD, endpoint="cost_report")
    _page(db_session, referenced, OLD, 0)
    _page(db_session, referenced, RECENT, 1)
    db_session.add(
        SpendCostLine(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=account_id,
            period_start=OLD,
            period_end=OLD,
            workspace_id=None,
            description="manual",
            cost_type="tokens",
            model="m",
            token_type="output_tokens",
            service_tier="standard",
            context_window="0-200k",
            inference_geo="global",
            amount=Decimal("1"),
            currency="USD",
            raw_amount_minor="1",
            sync_run_id=referenced.id,
        )
    )
    orphan = _sync(db_session, status="failed", finished=OLD, endpoint="usage")
    _page(db_session, orphan, RECENT, 0)
    running = _sync(db_session, status="running", finished=None, endpoint="inventory")
    _page(db_session, running, OLD, 0)
    recent = _sync(db_session, status="succeeded", finished=RECENT, endpoint="fresh")
    _page(db_session, recent, RECENT, 0)
    _scheduler(db_session, status="failed", finished=OLD)
    _scheduler(db_session, status="succeeded", finished=RECENT)
    _scheduler(db_session, status="queued", finished=None)
    _scheduler(db_session, status="running", finished=None)
    _scheduler(db_session, status="failed", finished=None)
    db_session.commit()

    counts = purge_mod.purge(db_session, now=NOW, page_days=90, run_days=90)

    assert counts.pages == 2
    assert counts.scheduler_runs == 1
    assert counts.sync_runs == 1
    assert counts.sync_runs_kept == 1
    assert db_session.get(ProviderSyncRun, referenced.id) is not None
    assert db_session.get(ProviderSyncRun, orphan.id) is None
    assert db_session.get(ProviderSyncRun, running.id) is not None
    assert db_session.get(ProviderSyncRun, recent.id) is not None
    remaining_pages = db_session.scalars(select(ProviderReportPage.sync_run_id)).all()
    assert sorted(remaining_pages) == sorted([referenced.id, recent.id])
    statuses = set(db_session.scalars(select(SchedulerRun.status)))
    assert statuses == {"succeeded", "queued", "running", "failed"}
    unfinished = set(
        db_session.scalars(select(SchedulerRun.status).where(SchedulerRun.finished_at.is_(None)))
    )
    assert unfinished == {"queued", "running", "failed"}


def test_purge_cli_prints_the_counts(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    assert purge_mod.main([]) == 0
    assert "pages=0" in capsys.readouterr().out


def test_worker_purges_once_per_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(worker, "purge_and_log", lambda: calls.append("purged"))

    assert worker.maintain(0.0, now=10.0) == 0.0
    assert calls == []
    assert worker.maintain(0.0, now=worker.PURGE_INTERVAL_SECONDS) == worker.PURGE_INTERVAL_SECONDS
    assert calls == ["purged"]


def test_worker_skips_ahead_when_purge_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(worker, "purge_and_log", boom)
    assert worker.maintain(0.0, now=worker.PURGE_INTERVAL_SECONDS) == worker.PURGE_INTERVAL_SECONDS
