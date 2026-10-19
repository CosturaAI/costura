"""Worker and scheduler process heartbeat behavior."""

import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models.heartbeat import WorkerHeartbeat
from costura.ops import heartbeat


def test_process_owner_contains_host_and_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(heartbeat.socket, "gethostname", lambda: "host-a")
    monkeypatch.setattr(heartbeat.os, "getpid", lambda: 42)
    assert heartbeat.process_owner() == "host-a:42"


def test_beat_inserts_then_updates_one_owner(db_session: Session) -> None:
    heartbeat.beat("worker", owner="process-1")
    first = db_session.get(WorkerHeartbeat, "process-1")
    assert first is not None
    assert first.role == "worker"
    first_seen = first.last_seen_at

    heartbeat.beat("scheduler", owner="process-1")
    db_session.expire_all()
    rows = list(db_session.scalars(select(WorkerHeartbeat)))
    assert len(rows) == 1
    assert rows[0].role == "scheduler"
    assert rows[0].last_seen_at >= first_seen


def test_beat_rejects_unknown_role() -> None:
    with pytest.raises(ValueError, match="unknown heartbeat role"):
        heartbeat.beat("api")


def test_last_seen_returns_newest_role_heartbeat(db_session: Session) -> None:
    old = datetime.now(UTC) - timedelta(minutes=2)
    new = datetime.now(UTC) - timedelta(seconds=2)
    db_session.add_all(
        [
            WorkerHeartbeat(owner="old", role="worker", last_seen_at=old, version="test"),
            WorkerHeartbeat(owner="new", role="worker", last_seen_at=new, version="test"),
            WorkerHeartbeat(
                owner="scheduler",
                role="scheduler",
                last_seen_at=datetime.now(UTC),
                version="test",
            ),
        ]
    )
    db_session.commit()
    assert heartbeat.last_seen("worker") == new
    assert heartbeat.last_seen("missing") is None


def test_fresh_handles_missing_stale_fresh_and_naive(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 10, 10, tzinfo=UTC)
    monkeypatch.setattr(heartbeat, "last_seen", lambda _role: None)
    assert heartbeat.fresh("worker", now=now) is False

    monkeypatch.setattr(heartbeat, "last_seen", lambda _role: now - timedelta(seconds=46))
    assert heartbeat.fresh("worker", max_age=45, now=now) is False
    monkeypatch.setattr(heartbeat, "last_seen", lambda _role: now - timedelta(seconds=45))
    assert heartbeat.fresh("worker", max_age=45, now=now) is True
    monkeypatch.setattr(heartbeat, "last_seen", lambda _role: datetime(2026, 10, 10))
    assert heartbeat.fresh("worker", max_age=0, now=now) is True


def test_main_returns_healthcheck_status(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(heartbeat, "fresh", lambda role, max_age: role == "worker")
    assert heartbeat.main(["--role", "worker", "--max-age", "12"]) == 0
    assert heartbeat.main(["--role", "scheduler"]) == 1
    assert "no fresh scheduler heartbeat" in capsys.readouterr().err


def test_worker_pulse_beats_until_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    from costura.ops import worker

    beats: list[int] = []
    monkeypatch.setattr(worker, "PULSE_SECONDS", 0.01)
    monkeypatch.setattr(worker, "_pulse", lambda: beats.append(1))
    stop = threading.Event()
    progress = [time.monotonic()]
    thread = threading.Thread(target=worker._pulse_until, args=(stop, progress))
    thread.start()
    while len(beats) < 3:
        stop.wait(0.01)
    stop.set()
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_worker_pulse_goes_quiet_when_the_loop_stalls(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    from costura.ops import worker

    beats: list[int] = []
    monkeypatch.setattr(worker, "PULSE_SECONDS", 0.01)
    monkeypatch.setattr(worker, "STALL_SECONDS", 0.0)
    monkeypatch.setattr(worker, "_pulse", lambda: beats.append(1))
    stopped: list[bool] = []
    stop = threading.Event()
    thread = threading.Thread(
        target=worker._pulse_until,
        args=(stop, [time.monotonic()]),
        kwargs={"terminate": lambda: stopped.append(True)},
    )
    thread.start()
    stop.wait(0.1)
    stop.set()
    thread.join(timeout=1)
    assert beats == []
    assert stopped == [True]
