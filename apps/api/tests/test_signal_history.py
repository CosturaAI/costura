"""Signal history: a stretch opens when an entity's signal appears, closes when it goes, a
second stretch counts as a recurrence, and stretches closed over 90 days ago are deleted."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import ProviderApiKey, SignalEvent
from costura.signal_history import record_history
from costura.spend.signal_events import closed_signals, occurrences
from tests.conftest import ORG_ID
from tests.test_delivery import _orphan_key

NOW = datetime.now(UTC)


def _events(db_session: Session, kind: str) -> list[SignalEvent]:
    return list(
        db_session.scalars(
            select(SignalEvent)
            .where(SignalEvent.organization_id == ORG_ID, SignalEvent.kind == kind)
            .order_by(SignalEvent.id)
        )
    )


def _key(db_session: Session) -> ProviderApiKey:
    key = db_session.scalar(
        select(ProviderApiKey).where(ProviderApiKey.external_id == "apikey_orphan")
    )
    assert key is not None
    return key


def test_a_gap_opens_closes_and_reopens_as_a_second_stretch(db_session: Session) -> None:
    _orphan_key(db_session)
    record_history(db_session, ORG_ID, now=NOW)
    (opened,) = _events(db_session, "no_owner")
    assert (opened.entity_id, opened.closed_at) == ("apikey_orphan", None)
    assert opened.label and opened.detail
    assert record_history(db_session, ORG_ID, now=NOW + timedelta(minutes=15)) == 0

    _key(db_session).status = "archived"
    db_session.flush()
    record_history(db_session, ORG_ID, now=NOW + timedelta(hours=2))
    (closed,) = _events(db_session, "no_owner")
    assert closed.closed_at == NOW + timedelta(hours=2)
    history = closed_signals(db_session, ORG_ID, now=NOW + timedelta(hours=3))
    assert ("no_owner", "apikey_orphan") in {(c.event.kind, c.event.entity_id) for c in history}

    _key(db_session).status = "active"
    db_session.flush()
    record_history(db_session, ORG_ID, now=NOW + timedelta(hours=4))
    assert [e.closed_at is None for e in _events(db_session, "no_owner")] == [False, True]
    counts = occurrences(db_session, ORG_ID, now=NOW + timedelta(hours=4))
    assert counts[("no_owner", "anthropic", "api_key", "apikey_orphan")] == 2


def test_stretches_closed_over_ninety_days_ago_are_deleted(db_session: Session) -> None:
    _orphan_key(db_session)
    record_history(db_session, ORG_ID, now=NOW)
    _key(db_session).status = "archived"
    db_session.flush()
    record_history(db_session, ORG_ID, now=NOW + timedelta(hours=1))
    assert _events(db_session, "no_owner")
    record_history(db_session, ORG_ID, now=NOW + timedelta(days=91, hours=2))
    assert _events(db_session, "no_owner") == []


def test_routes_list_closed_signals_and_count_recurrences(
    client: TestClient, db_session: Session
) -> None:
    _orphan_key(db_session)
    record_history(db_session, ORG_ID, now=NOW - timedelta(hours=3))
    _key(db_session).status = "archived"
    db_session.flush()
    record_history(db_session, ORG_ID, now=NOW - timedelta(hours=2))
    _key(db_session).status = "active"
    db_session.flush()
    record_history(db_session, ORG_ID, now=NOW - timedelta(hours=1))
    db_session.commit()

    slug = client.get("/api/v1/orgs").json()[0]["slug"]
    history = client.get(f"/api/v1/orgs/{slug}/signals/history").json()["items"]
    gap = next(i for i in history if i["kind"] == "no_owner")
    assert (gap["entity_id"], gap["hours_open"]) == ("apikey_orphan", "1.0")
    items = client.get(f"/api/v1/orgs/{slug}/providers/all/signals").json()["items"]
    current = next(i for i in items if i["kind"] == "no_owner")
    assert current["occurrences"] == 2
