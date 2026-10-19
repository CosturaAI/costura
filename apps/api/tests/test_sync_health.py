"""A connected account whose cost import stopped is a signal until the next success."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from costura.models import ProviderCredential, ProviderSyncRun
from costura.spend.signals import collect_signals
from costura.spend.sync_health import unhealthy_accounts
from tests.conftest import ORG_ID, account_of

TODAY = date(2026, 10, 15)


def _connected(session: Session, *, error: str | None = None) -> int:
    account = account_of(session, ORG_ID, "anthropic")
    session.add(
        ProviderCredential(
            organization_id=ORG_ID,
            provider="anthropic",
            account_id=account,
            key_digest="d",
            ciphertext=b"x",
            key_hint="1234",
            last_error=error,
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    session.flush()
    return account


def _run(session: Session, account: int, status: str, finished: datetime) -> None:
    session.add(
        ProviderSyncRun(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=account,
            endpoint="cost_report",
            window_start=datetime(2026, 10, 1, tzinfo=UTC),
            window_end=datetime(2026, 11, 1, tzinfo=UTC),
            started_at=finished,
            finished_at=finished,
            status=status,
        )
    )
    session.flush()


def _reasons(session: Session) -> list[str]:
    return [h.reason for h in unhealthy_accounts(session, ORG_ID, "anthropic", TODAY)]


def test_a_fresh_account_raises_nothing(db_session: Session) -> None:
    account = _connected(db_session)
    _run(db_session, account, "succeeded", datetime(2026, 10, 15, 6, tzinfo=UTC))
    assert _reasons(db_session) == []


def test_each_cause_raises_a_sync_signal_and_a_success_closes_it(db_session: Session) -> None:
    account = _connected(db_session)
    assert _reasons(db_session) == ["no cost import has succeeded since the key was connected"]

    _run(db_session, account, "succeeded", datetime(2026, 10, 11, 6, tzinfo=UTC))
    assert _reasons(db_session) == ["no cost import has succeeded since 2026-10-11"]

    _run(db_session, account, "failed", datetime(2026, 10, 15, 6, tzinfo=UTC))
    assert _reasons(db_session) == ["the latest cost import failed"]
    found = [
        s for s in collect_signals(db_session, ORG_ID, "all", today=TODAY) if s.kind == "sync_stale"
    ]
    assert [(s.entity_kind, s.reference) for s in found] == [("provider_account", str(account))]

    _run(db_session, account, "succeeded", datetime(2026, 10, 15, 7, tzinfo=UTC))
    assert _reasons(db_session) == []


def test_a_refused_key_is_named(db_session: Session) -> None:
    account = _connected(db_session, error="Anthropic rejected the key (HTTP 401).")
    _run(db_session, account, "succeeded", datetime(2026, 10, 15, 6, tzinfo=UTC))
    assert _reasons(db_session) == ["the provider refused the key"]


def test_a_disconnected_or_keyless_account_is_not_watched(db_session: Session) -> None:
    account = account_of(db_session, ORG_ID, "anthropic")
    _run(db_session, account, "failed", datetime(2026, 10, 15, 6, tzinfo=UTC) - timedelta(days=5))
    assert _reasons(db_session) == []


def test_imports_that_report_no_spend_after_spending_are_flagged(db_session: Session) -> None:
    from decimal import Decimal

    from costura.models import SpendCostLine

    account = _connected(db_session)
    _run(db_session, account, "succeeded", datetime(2026, 10, 15, 6, tzinfo=UTC))
    run_id = db_session.query(ProviderSyncRun.id).first()[0]

    def spend_on(day: int) -> None:
        start = datetime(2026, 10, day, tzinfo=UTC)
        db_session.add(
            SpendCostLine(
                organization_id=ORG_ID,
                provider="anthropic",
                provider_account_id=account,
                period_start=start,
                period_end=start,
                workspace_id=None,
                description="manual",
                cost_type="tokens",
                model="m",
                token_type="output_tokens",
                service_tier="standard",
                context_window="0-200k",
                inference_geo="global",
                amount=Decimal("30"),
                currency="USD",
                raw_amount_minor="30",
                sync_run_id=run_id,
            )
        )
        db_session.flush()

    spend_on(5)
    assert _reasons(db_session) == ["the provider has reported no spend since 2026-10-05"]
    spend_on(13)
    assert _reasons(db_session) == []
