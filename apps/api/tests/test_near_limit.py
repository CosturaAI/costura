"""Hard provider limits at 80% used are signals, with what is left as the money."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from costura.models import ProviderApiKey, ProviderLimit
from costura.spend.signals import collect_signals
from tests.conftest import ORG_ID, account_of
from tests.seed import sync_run


def _near(session: Session, provider: str) -> list[tuple[str, Decimal]]:
    return [
        (s.entity_id, s.dollars_at_risk)
        for s in collect_signals(session, ORG_ID, provider)
        if s.kind == "near_limit"
    ]


def test_an_openrouter_key_at_80_percent_of_its_limit(db_session: Session) -> None:
    today = datetime.now(UTC).date()
    run = sync_run(db_session, ORG_ID, "openrouter", "keys", today, today)
    for external_id, remaining in (("orkey_hot", "15"), ("orkey_cool", "60")):
        db_session.add(
            ProviderApiKey(
                organization_id=ORG_ID,
                provider="openrouter",
                provider_account_id=account_of(db_session, ORG_ID, "openrouter"),
                sync_run_id=run.id,
                external_id=external_id,
                name=external_id,
                status="active",
                limit_reported=True,
                spend_limit=Decimal("100"),
                limit_remaining=Decimal(remaining),
                limit_reset="monthly",
            )
        )
    db_session.flush()
    assert _near(db_session, "openrouter") == [("orkey_hot", Decimal("15"))]


def test_a_reported_budget_near_its_amount(db_session: Session) -> None:
    today = datetime.now(UTC).date()
    run = sync_run(db_session, ORG_ID, "copilot", "budgets", today, today)
    db_session.add(
        ProviderLimit(
            organization_id=ORG_ID,
            provider="copilot",
            provider_account_id=account_of(db_session, ORG_ID, "copilot"),
            sync_run_id=run.id,
            external_id="budget-1",
            scope_kind="organization",
            scope_name="acme-inc Copilot",
            product="copilot",
            amount=Decimal("500"),
            consumed=Decimal("450"),
            enforcement="hard",
        )
    )
    db_session.flush()
    assert _near(db_session, "copilot") == [("acme-inc Copilot", Decimal("50"))]
