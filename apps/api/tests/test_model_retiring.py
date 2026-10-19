"""Keys still spending on a model the catalog retires soon are signals."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from costura.spend.signals import collect_signals
from tests.conftest import ORG_ID
from tests.seed import seed_days


def _plan(model: str):
    def plan(day: date) -> list[tuple[str | None, str, str, Decimal]]:
        return [("ws_a", model, "apikey_batch", Decimal("12"))]

    return plan


def _retiring(session: Session, today: date) -> list[tuple[str, str]]:
    return [
        (s.entity_id, s.model or "")
        for s in collect_signals(session, ORG_ID, "anthropic", today=today)
        if s.kind == "model_retiring"
    ]


def test_a_key_on_a_model_retiring_within_60_days_is_a_signal(db_session: Session) -> None:
    seed_days(
        db_session,
        ORG_ID,
        "anthropic",
        date(2026, 10, 1),
        date(2026, 10, 15),
        _plan("claude-sonnet-4-5"),
    )
    assert _retiring(db_session, date(2026, 10, 15)) == [("apikey_batch", "claude-sonnet-4-5")]
    assert _retiring(db_session, date(2026, 9, 1)) == []


def test_it_closes_after_a_week_without_spend_on_that_model(db_session: Session) -> None:
    seed_days(
        db_session,
        ORG_ID,
        "anthropic",
        date(2026, 10, 1),
        date(2026, 10, 5),
        _plan("claude-sonnet-4-5"),
    )
    assert _retiring(db_session, date(2026, 10, 15)) == []
