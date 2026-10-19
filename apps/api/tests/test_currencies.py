"""Spend billed in more than one currency is reported per currency, not as one sum."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from costura.models import ProviderSyncRun, SpendCostLine
from costura.spend.summary import summary
from tests.conftest import ORG_ID, account_of


def _line(session: Session, day: int, amount: str, currency: str) -> None:
    account = account_of(session, ORG_ID, "anthropic")
    start = datetime(2026, 8, day, tzinfo=UTC)
    run = ProviderSyncRun(
        organization_id=ORG_ID,
        provider="anthropic",
        provider_account_id=account,
        endpoint="cost_report",
        window_start=start,
        window_end=start,
        status="succeeded",
    )
    session.add(run)
    session.flush()
    session.add(
        SpendCostLine(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=account,
            period_start=start,
            period_end=start,
            workspace_id=None,
            description=f"manual {currency}",
            cost_type="tokens",
            model="m",
            token_type="output_tokens",
            service_tier="standard",
            context_window="0-200k",
            inference_geo="global",
            amount=Decimal(amount),
            currency=currency,
            raw_amount_minor=amount,
            sync_run_id=run.id,
        )
    )
    session.flush()


def test_one_currency_has_no_per_currency_split(db_session: Session) -> None:
    _line(db_session, 3, "10", "USD")
    found = summary(
        db_session, org_id=ORG_ID, provider="anthropic", month="2026-08", today=date(2026, 10, 1)
    )
    assert (found.currency, found.currency_totals) == ("USD", None)


def test_mixed_currencies_come_back_per_currency(db_session: Session) -> None:
    _line(db_session, 3, "10", "USD")
    _line(db_session, 4, "7.5", "EUR")
    found = summary(
        db_session, org_id=ORG_ID, provider="anthropic", month="2026-08", today=date(2026, 10, 1)
    )
    assert found.currency is None
    assert found.currency_totals == {"EUR": Decimal("7.5"), "USD": Decimal("10")}
