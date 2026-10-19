"""Idle paid seats and members without a spend limit are snoozable signals."""

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from costura.models import ProviderUser
from costura.spend import snoozes
from costura.spend.signals import collect_signals
from tests.conftest import ORG_ID, account_of
from tests.seed import sync_run

TODAY = date(2026, 10, 15)


def _member(session: Session, external_id: str, **fields: object) -> None:
    run = sync_run(session, ORG_ID, "cursor", "members", TODAY, TODAY)
    session.add(
        ProviderUser(
            organization_id=ORG_ID,
            provider="cursor",
            provider_account_id=account_of(session, ORG_ID, "cursor"),
            sync_run_id=run.id,
            external_id=external_id,
            email=f"{external_id}@example.com",
            role="member",
            **fields,
        )
    )
    session.flush()


def _seats(session: Session) -> set[tuple[str, str]]:
    return {
        (s.kind, s.entity_id)
        for s in collect_signals(session, ORG_ID, "cursor", today=TODAY)
        if s.kind in ("idle_seat", "seat_no_limit")
    }


def test_idle_seats_and_members_without_a_limit(db_session: Session) -> None:
    _member(db_session, "ana", last_active_at=datetime(2026, 8, 1, tzinfo=UTC))
    _member(db_session, "bruno", last_active_at=datetime(2026, 10, 14, tzinfo=UTC))
    _member(db_session, "carla", last_active_at=None, limit_reported=True, spend_limit=None)
    assert _seats(db_session) == {("idle_seat", "ana"), ("seat_no_limit", "carla")}

    snoozes.snooze(
        db_session,
        ORG_ID,
        "cursor",
        kind="idle_seat",
        key_id="ana",
        days=30,
        note="on leave",
        user_id=None,
        today=TODAY,
    )
    assert _seats(db_session) == {("seat_no_limit", "carla")}
