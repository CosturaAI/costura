"""Budget alerts and key governance gaps in the member's inbox: what counts as unread after
the opt-in, read marks per signal, and what a new threshold or an opt-out does to them."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from costura.models import OrganizationMember, SignalRead, SpendBudgetAlert, User
from costura.orgs import get_org
from costura.spend.inbox import (
    mark_signals_read,
    read_key,
    set_inbox_opt_in,
    signal_inbox,
)
from tests.conftest import SAMPLE_TODAY, seed_sample
from tests.support.orgs import add_member


def _member(db_session: Session) -> tuple[int, int, datetime]:
    org = seed_sample(db_session).organization
    user = User(email="ana@example.com")
    db_session.add(user)
    db_session.flush()
    add_member(db_session, get_org(db_session, org.slug), user, "member")
    set_inbox_opt_in(db_session, org.id, user.id, True, today=SAMPLE_TODAY)
    since = datetime(2026, 9, 1, tzinfo=UTC)
    db_session.execute(
        update(OrganizationMember)
        .where(OrganizationMember.user_id == user.id)
        .values(anomaly_alerts_since=since)
    )
    return org.id, user.id, since


def test_gaps_that_exist_at_the_opt_in_start_read_and_budget_alerts_after_it_unread(
    db_session: Session,
) -> None:
    org_id, user_id, since = _member(db_session)
    items = signal_inbox(db_session, org_id, user_id, since, today=SAMPLE_TODAY)

    budgets = [i for i in items if i.signal.kind == "budget"]
    gaps = [i for i in items if i.signal.kind != "budget"]
    assert budgets and gaps
    assert all(i.read_at is None for i in budgets)
    assert all(i.read_at is not None for i in gaps)
    amounts = [i.signal.dollars_at_risk for i in items]
    assert amounts == sorted(amounts, reverse=True)


def test_a_read_mark_names_the_alert_so_the_next_threshold_is_unread_again(
    db_session: Session,
) -> None:
    org_id, user_id, since = _member(db_session)
    budget = next(
        i
        for i in signal_inbox(db_session, org_id, user_id, since, today=SAMPLE_TODAY)
        if i.signal.kind == "budget"
    )
    assert budget.signal.alert is not None
    assert read_key(budget.signal)[2] == str(budget.signal.alert.id)

    mark_signals_read(
        db_session,
        org_id,
        user_id,
        every_unread=False,
        keys=[budget.key, ("budget", "anthropic", "999999")],
        today=SAMPLE_TODAY,
    )
    again = signal_inbox(db_session, org_id, user_id, since, today=SAMPLE_TODAY)
    assert next(i for i in again if i.key == budget.key).read_at is not None
    assert (
        db_session.scalar(
            select(func.count()).select_from(SignalRead).where(SignalRead.reference == "999999")
        )
        == 0
    )

    crossed = budget.signal.alert
    newer = SpendBudgetAlert(
        organization_id=crossed.organization_id,
        provider=crossed.provider,
        budget_id=crossed.budget_id,
        month=crossed.month,
        kind="threshold",
        threshold=99,
        amount=crossed.amount,
        spent=crossed.spent,
        projected=crossed.projected,
        currency=crossed.currency,
        triggered_at=crossed.triggered_at + timedelta(hours=1),
    )
    db_session.add(newer)
    db_session.flush()
    latest = signal_inbox(db_session, org_id, user_id, since, today=SAMPLE_TODAY)
    assert (
        next(
            i
            for i in latest
            if i.signal.kind == "budget" and i.signal.reference == budget.signal.reference
        ).read_at
        is None
    )


def test_mark_all_reads_every_signal_and_opting_out_forgets_the_marks(
    db_session: Session,
) -> None:
    org_id, user_id, since = _member(db_session)
    mark_signals_read(db_session, org_id, user_id, every_unread=True, today=SAMPLE_TODAY)
    items = signal_inbox(db_session, org_id, user_id, since, today=SAMPLE_TODAY)
    assert items and all(i.read_at is not None for i in items)

    set_inbox_opt_in(db_session, org_id, user_id, False, today=SAMPLE_TODAY)
    assert db_session.scalar(select(func.count()).select_from(SignalRead)) == 0
    mark_signals_read(db_session, org_id, user_id, every_unread=True, today=SAMPLE_TODAY)
    assert db_session.scalar(select(func.count()).select_from(SignalRead)) == 0
