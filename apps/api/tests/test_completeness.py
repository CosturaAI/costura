"""How far billed spend is complete per account, and when a failed sync makes it stale."""

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from costura.models import ProviderSyncRun
from costura.spend.completeness import completeness
from tests.conftest import ORG_ID, account_of


def _run(
    session: Session,
    account: int,
    *,
    status: str,
    end: datetime,
    finished: datetime,
    endpoint: str = "cost_report",
) -> None:
    session.add(
        ProviderSyncRun(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=account,
            endpoint=endpoint,
            window_start=datetime(2026, 10, 1, tzinfo=UTC),
            window_end=end,
            started_at=finished,
            finished_at=finished,
            status=status,
        )
    )
    session.flush()


def test_a_month_in_progress_is_complete_through_the_day_before_the_sync(
    db_session: Session,
) -> None:
    account = account_of(db_session, ORG_ID, "anthropic")
    assert completeness(db_session, ORG_ID, "anthropic").complete_through is None
    month_end = datetime(2026, 11, 1, tzinfo=UTC)
    _run(
        db_session,
        account,
        status="succeeded",
        end=month_end,
        finished=datetime(2026, 10, 13, 6, tzinfo=UTC),
    )
    _run(
        db_session,
        account,
        status="succeeded",
        end=month_end,
        finished=datetime(2026, 10, 13, 6, tzinfo=UTC),
        endpoint="usage_report",
    )
    found = completeness(db_session, ORG_ID, "anthropic")
    assert (found.complete_through, found.stale) == (date(2026, 10, 12), False)
    assert completeness(db_session, ORG_ID, "all").complete_through == date(2026, 10, 12)


def test_a_failed_sync_keeps_the_last_success_and_marks_it_stale(db_session: Session) -> None:
    account = account_of(db_session, ORG_ID, "anthropic")
    month_end = datetime(2026, 11, 1, tzinfo=UTC)
    _run(
        db_session,
        account,
        status="succeeded",
        end=month_end,
        finished=datetime(2026, 10, 10, 6, tzinfo=UTC),
    )
    _run(
        db_session,
        account,
        status="failed",
        end=month_end,
        finished=datetime(2026, 10, 14, 6, tzinfo=UTC),
    )
    found = completeness(db_session, ORG_ID, "anthropic")
    assert (found.complete_through, found.stale) == (date(2026, 10, 9), True)


def test_a_closed_month_is_complete_through_its_last_day(db_session: Session) -> None:
    account = account_of(db_session, ORG_ID, "anthropic")
    _run(
        db_session,
        account,
        status="succeeded",
        end=datetime(2026, 10, 1, tzinfo=UTC),
        finished=datetime(2026, 10, 14, 6, tzinfo=UTC),
    )
    assert completeness(db_session, ORG_ID, "anthropic").complete_through == date(2026, 9, 30)


def test_a_failed_current_month_is_stale_although_the_previous_month_succeeded_later(
    db_session: Session,
) -> None:
    account = account_of(db_session, ORG_ID, "anthropic")

    def run(window_start: datetime, end: datetime, status: str, finished: datetime) -> None:
        db_session.add(
            ProviderSyncRun(
                organization_id=ORG_ID,
                provider="anthropic",
                provider_account_id=account,
                endpoint="cost_report",
                window_start=window_start,
                window_end=end,
                started_at=finished,
                finished_at=finished,
                status=status,
            )
        )
        db_session.flush()

    october, september = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC)
    november = datetime(2026, 11, 1, tzinfo=UTC)
    run(october, november, "succeeded", datetime(2026, 10, 14, 6, tzinfo=UTC))
    run(september, october, "succeeded", datetime(2026, 10, 14, 6, 5, tzinfo=UTC))
    run(october, november, "failed", datetime(2026, 10, 15, 6, tzinfo=UTC))
    run(september, october, "succeeded", datetime(2026, 10, 15, 6, 5, tzinfo=UTC))

    found = completeness(db_session, ORG_ID, "anthropic")
    assert (found.complete_through, found.stale) == (date(2026, 10, 13), True)


def test_a_disconnected_account_no_longer_holds_completeness_back(db_session: Session) -> None:
    from costura import credentials
    from costura.models import ProviderAccount, ProviderCredential

    first = account_of(db_session, ORG_ID, "anthropic")
    second = ProviderAccount(organization_id=ORG_ID, provider="anthropic", label="Second")
    db_session.add(second)
    db_session.flush()
    month_end = datetime(2026, 11, 1, tzinfo=UTC)
    _run(
        db_session,
        first,
        status="succeeded",
        end=month_end,
        finished=datetime(2026, 10, 14, 6, tzinfo=UTC),
    )
    _run(
        db_session,
        second.id,
        status="succeeded",
        end=month_end,
        finished=datetime(2026, 10, 3, 6, tzinfo=UTC),
    )
    assert completeness(db_session, ORG_ID, "anthropic").complete_through == date(2026, 10, 2)

    db_session.add(
        ProviderCredential(
            organization_id=ORG_ID,
            provider="anthropic",
            account_id=second.id,
            key_digest="d",
            ciphertext=b"x",
            key_hint="1234",
        )
    )
    db_session.flush()
    assert credentials.clear_credential(db_session, ORG_ID, "anthropic", second.id)
    assert second.disconnected_at is not None
    assert completeness(db_session, ORG_ID, "anthropic").complete_through == date(2026, 10, 13)


def test_detection_through_lags_when_detection_was_skipped(db_session: Session) -> None:
    account = account_of(db_session, ORG_ID, "anthropic")
    month_end = datetime(2026, 11, 1, tzinfo=UTC)
    _run(
        db_session,
        account,
        status="succeeded",
        end=month_end,
        finished=datetime(2026, 10, 15, 6, tzinfo=UTC),
    )
    _run(
        db_session,
        account,
        status="succeeded",
        end=month_end,
        finished=datetime(2026, 10, 11, 6, tzinfo=UTC),
        endpoint="anomaly_detection",
    )
    found = completeness(db_session, ORG_ID, "anthropic")
    assert (found.complete_through, found.detection_through) == (
        date(2026, 10, 14),
        date(2026, 10, 10),
    )
