"""Money and tenant invariants of the spend core over PostgreSQL: a failed allocation leaves the
previous one in place, one organization's runs and reads never touch another's rows, and the
billed query falls back to cost lines without changing the total."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import ProviderSyncRun, SpendAllocatedLine
from costura.models.allocation import ALLOCATION_ENDPOINT
from costura.models.organization import Organization
from costura.spend.allocate import run_allocation
from costura.spend.query import QuerySpec, query_spend
from costura.spend.window import Window
from tests.conftest import ORG_ID
from tests.seed import Line, seed_days

PROVIDER = "anthropic"
AUGUST = Window.for_month("2026-08")
START, END = date(2026, 8, 1), date(2026, 8, 11)


def plan_of(workspace: str, key: str, amount: str):
    def plan(_day: date) -> list[Line]:
        return [(workspace, "claude-sonnet-4", key, Decimal(amount))]

    return plan


def allocated(session: Session, org_id: int) -> tuple[int, Decimal]:
    count, total = session.execute(
        select(func.count(), func.coalesce(func.sum(SpendAllocatedLine.amount), 0)).where(
            SpendAllocatedLine.organization_id == org_id
        )
    ).one()
    return count, Decimal(total)


def billed(session: Session, org_id: int, start: date, end: date):
    return query_spend(
        session,
        org_id=org_id,
        spec=QuerySpec(
            measure="billed_usd",
            dimensions=(),
            filters={"provider": PROVIDER},
            start=start,
            end=end,
            interval="month",
            top=8,
        ),
    )


def test_a_failed_allocation_keeps_the_previous_rows_and_records_the_failure(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_days(db_session, ORG_ID, PROVIDER, START, END, plan_of("wrk-a", "key-a", "100"))
    db_session.commit()
    run_allocation(db_session, ORG_ID, PROVIDER, AUGUST)
    before = allocated(db_session, ORG_ID)
    assert before == (10, Decimal("1000"))

    def explode(*_args: object, **_kwargs: object) -> list:
        raise RuntimeError("strategy failed")

    monkeypatch.setattr("costura.spend.allocate.split_by_tokens", explode)
    with pytest.raises(RuntimeError, match="strategy failed"):
        run_allocation(db_session, ORG_ID, PROVIDER, AUGUST)

    assert allocated(db_session, ORG_ID) == before
    last = db_session.scalars(
        select(ProviderSyncRun)
        .where(
            ProviderSyncRun.organization_id == ORG_ID,
            ProviderSyncRun.endpoint == ALLOCATION_ENDPOINT,
        )
        .order_by(ProviderSyncRun.id.desc())
    ).first()
    assert last is not None
    assert last.status == "failed"
    assert last.error == "RuntimeError: strategy failed"


def test_allocation_and_query_stay_inside_one_organization(db_session: Session) -> None:
    other = Organization(slug="tenant-b", name="Tenant B")
    db_session.add(other)
    db_session.flush()
    seed_days(db_session, ORG_ID, PROVIDER, START, END, plan_of("wrk-a", "key-a", "100"))
    seed_days(db_session, other.id, PROVIDER, START, END, plan_of("wrk-b", "key-b", "7"))
    db_session.commit()
    other_before = allocated(db_session, other.id)

    run_allocation(db_session, ORG_ID, PROVIDER, AUGUST)

    assert allocated(db_session, other.id) == other_before
    assert sum(billed(db_session, ORG_ID, START, date(2026, 8, 10)).total) == Decimal("1000")
    assert sum(billed(db_session, other.id, START, date(2026, 8, 10)).total) == Decimal("70")


def test_billed_query_falls_back_to_cost_lines_when_allocation_covers_part_of_the_range(
    db_session: Session,
) -> None:
    july = date(2026, 7, 29)
    seed_days(db_session, ORG_ID, PROVIDER, july, START, plan_of("wrk-a", "key-a", "10"))
    seed_days(db_session, ORG_ID, PROVIDER, START, END, plan_of("wrk-a", "key-a", "100"))
    db_session.commit()

    across = billed(db_session, ORG_ID, july, date(2026, 8, 4))
    assert across.source == "allocated"
    assert sum(across.total) == Decimal("430")

    july_run = db_session.scalars(
        select(ProviderSyncRun).where(
            ProviderSyncRun.organization_id == ORG_ID,
            ProviderSyncRun.endpoint == ALLOCATION_ENDPOINT,
            ProviderSyncRun.window_start < datetime(2026, 8, 1, tzinfo=UTC),
        )
    ).one()
    july_run.status = "failed"
    db_session.commit()

    covered = billed(db_session, ORG_ID, START, date(2026, 8, 5))
    partial = billed(db_session, ORG_ID, july, date(2026, 8, 5))
    assert covered.source == "allocated"
    assert partial.source == "cost"
    assert sum(covered.total) == Decimal("500")
    assert sum(partial.total) == Decimal("530")
