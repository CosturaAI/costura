"""A key whose cost per token rises at a steady volume is a signal; a key that only spends
more is not."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from costura.spend.signals import collect_signals
from tests.conftest import ORG_ID
from tests.seed import seed_days

TODAY = date(2026, 10, 15)
SWITCH = TODAY - timedelta(days=7)


def _units(session: Session) -> list[str]:
    return [
        s.entity_id
        for s in collect_signals(session, ORG_ID, "anthropic", today=TODAY)
        if s.kind == "unit_cost_up"
    ]


def test_a_model_switch_at_the_same_volume_is_flagged(db_session: Session) -> None:
    def plan(day: date) -> list[tuple[str | None, str, str, Decimal]]:
        if day < SWITCH:
            return [("ws_a", "claude-sonnet-4", "apikey_agent", Decimal("10"))]
        return [("ws_a", "claude-opus-4-1", "apikey_agent", Decimal("50"))]

    seed_days(db_session, ORG_ID, "anthropic", TODAY - timedelta(days=40), TODAY, plan)
    assert _units(db_session) == ["apikey_agent"]


def test_more_use_at_the_same_price_is_not(db_session: Session) -> None:
    def plan(day: date) -> list[tuple[str | None, str, str, Decimal]]:
        amount = Decimal("30") if day >= SWITCH else Decimal("10")
        return [("ws_a", "claude-sonnet-4", "apikey_agent", amount)]

    seed_days(db_session, ORG_ID, "anthropic", TODAY - timedelta(days=40), TODAY, plan)
    assert _units(db_session) == []
