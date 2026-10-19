"""Snoozed key gaps leave the signals queue and the inbox until their date, and come back."""

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import AuditEvent, ProviderApiKey
from costura.spend import snoozes
from costura.spend.signals import collect_signals
from tests.conftest import ORG_ID, account_of
from tests.seed import sync_run

SNOOZES = "/api/v1/orgs/default/providers/anthropic/signals/snoozes"
SIGNALS = "/api/v1/orgs/default/providers/anthropic/signals"


def _orphan_key(session: Session) -> None:
    today = datetime.now(UTC).date()
    run = sync_run(session, ORG_ID, "anthropic", "api_keys", today, today)
    session.add(
        ProviderApiKey(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=account_of(session, ORG_ID, "anthropic"),
            sync_run_id=run.id,
            external_id="apikey_orphan",
            name="orphan",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            status="active",
        )
    )
    session.commit()


def _kinds(session: Session, today: date) -> set[str]:
    return {s.kind for s in collect_signals(session, ORG_ID, "anthropic", today=today)}


def test_a_snoozed_gap_leaves_the_queue_until_its_date(db_session: Session) -> None:
    _orphan_key(db_session)
    today = date(2026, 10, 15)
    assert {"no_owner", "idle_active"} <= _kinds(db_session, today)

    row = snoozes.snooze(
        db_session,
        ORG_ID,
        "anthropic",
        kind="no_owner",
        key_id="apikey_orphan",
        days=7,
        note="shared service key",
        user_id=None,
        today=today,
    )
    assert row.until == today + timedelta(days=7)
    assert "no_owner" not in _kinds(db_session, today)
    assert "idle_active" in _kinds(db_session, today)
    assert "no_owner" in _kinds(db_session, today + timedelta(days=7))

    assert snoozes.lift(db_session, ORG_ID, "anthropic", kind="no_owner", key_id="apikey_orphan")
    assert "no_owner" in _kinds(db_session, today)


def test_routes_snooze_list_and_lift_with_an_audit_trail(
    client: TestClient, db_session: Session
) -> None:
    _orphan_key(db_session)
    body = {"kind": "no_owner", "key_id": "apikey_orphan", "days": 30, "note": "on purpose"}
    snoozed = client.put(SNOOZES, json=body)
    assert snoozed.status_code == 200, snoozed.text
    assert snoozed.json()["note"] == "on purpose"

    listed = client.get(SIGNALS).json()
    assert ("no_owner", "apikey_orphan") not in {
        (s["kind"], s["entity_id"]) for s in listed["items"]
    }
    assert [(s["kind"], s["key_id"]) for s in listed["snoozed"]] == [("no_owner", "apikey_orphan")]

    assert client.put(SNOOZES, json={**body, "days": 10}).status_code == 422
    assert client.put(SNOOZES, json={**body, "kind": "budget"}).status_code == 422
    assert client.put(SNOOZES, json={**body, "key_id": "missing"}).status_code == 404
    assert client.put(
        "/api/v1/orgs/default/providers/all/signals/snoozes", json=body
    ).status_code in (400, 404, 422)

    assert client.delete(f"{SNOOZES}/no_owner/apikey_orphan").status_code == 204
    assert client.get(SIGNALS).json()["snoozed"] == []
    db_session.expire_all()
    events = [e.event for e in db_session.scalars(select(AuditEvent).order_by(AuditEvent.id))]
    assert events == ["signal_snoozed", "signal_snooze_lifted"]
