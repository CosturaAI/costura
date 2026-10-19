from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from costura import __version__
from costura.db import get_engine
from costura.main import app


def test_live_does_not_touch_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> None:
        raise AssertionError("live must not open a database connection")

    monkeypatch.setattr(get_engine(), "connect", fail)
    response = TestClient(app).get("/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_ok_and_database_round_trip(client: TestClient) -> None:
    response = client.get("/health")
    ready = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "env": "test",
        "database": "ok",
        "version": __version__,
    }
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok", "database": "ok"}


def test_ready_and_health_are_503_when_the_database_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_engine(), "connect", MagicMock(side_effect=SQLAlchemyError("down")))
    client = TestClient(app)

    ready = client.get("/ready")
    health = client.get("/health")

    assert ready.status_code == 503
    assert ready.json() == {"detail": "database unreachable"}
    assert health.status_code == 503
    assert health.json() == {"detail": "database unreachable"}
