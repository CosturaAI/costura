"""Aggregate non-completions activity and match it to billed cost families."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.errors import InvalidInput
from costura.models import SpendActivityLine, SpendCostLine

FAMILY_COST_TYPE = {
    "images": "images",
    "embeddings": "embeddings",
    "moderations": "moderations",
    "audio_speeches": "audio",
    "audio_transcriptions": "audio",
    "vector_stores": "vector_stores",
    "code_interpreter_sessions": "code_interpreter",
}


@dataclass(frozen=True)
class ActivityRow:
    family: str
    unit: str
    quantity: Decimal
    requests: int
    billed_usd: Decimal

    @property
    def cost_per_unit(self) -> Decimal | None:
        return None if self.quantity == 0 else self.billed_usd / self.quantity


@dataclass(frozen=True)
class ActivityReport:
    rows: list[ActivityRow]
    total: int


def activity_report(
    session: Session,
    *,
    org_id: int,
    since: date,
    until: date,
    family: str | None = None,
    provider_account_id: int | None = None,
    workspace_id: str | None = None,
    api_key_id: str | None = None,
    limit: int | None = None,
) -> ActivityReport:
    """One row per (family, unit) in family order, at most `limit`, and how many there are."""
    if since > until:
        raise InvalidInput("since must be on or before until")
    if family is not None and family not in FAMILY_COST_TYPE:
        raise InvalidInput(f"unknown activity family {family!r}")

    start = datetime.combine(since, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(until + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    activity_where = [
        SpendActivityLine.organization_id == org_id,
        SpendActivityLine.period_start >= start,
        SpendActivityLine.period_start < end,
    ]
    cost_where = [
        SpendCostLine.organization_id == org_id,
        SpendCostLine.period_start >= start,
        SpendCostLine.period_start < end,
    ]
    if family is not None:
        activity_where.append(SpendActivityLine.family == family)
    if provider_account_id is not None:
        activity_where.append(SpendActivityLine.provider_account_id == provider_account_id)
        cost_where.append(SpendCostLine.provider_account_id == provider_account_id)
    if workspace_id is not None:
        activity_where.append(SpendActivityLine.workspace_id == workspace_id)
        cost_where.append(SpendCostLine.workspace_id == workspace_id)
    if api_key_id is not None:
        activity_where.append(SpendActivityLine.api_key_id == api_key_id)
        cost_where.append(SpendCostLine.api_key_id == api_key_id)

    grouped = (
        select(
            SpendActivityLine.family,
            SpendActivityLine.unit,
            func.sum(SpendActivityLine.quantity),
            func.sum(SpendActivityLine.request_count),
        )
        .where(*activity_where)
        .group_by(SpendActivityLine.family, SpendActivityLine.unit)
    )
    total = session.scalar(select(func.count()).select_from(grouped.subquery())) or 0
    ordered = grouped.order_by(SpendActivityLine.family, SpendActivityLine.unit)
    rows = session.execute(ordered if limit is None else ordered.limit(limit)).all()
    cost_types = {FAMILY_COST_TYPE[row.family] for row in rows}
    billed = {
        cost_type: Decimal(amount)
        for cost_type, amount in session.execute(
            select(SpendCostLine.cost_type, func.sum(SpendCostLine.amount))
            .where(*cost_where, SpendCostLine.cost_type.in_(cost_types))
            .group_by(SpendCostLine.cost_type)
        ).all()
    }
    return ActivityReport(
        rows=[
            ActivityRow(
                family=row.family,
                unit=row.unit,
                quantity=Decimal(row[2]),
                requests=int(row[3]),
                billed_usd=billed.get(FAMILY_COST_TYPE[row.family], Decimal("0")),
            )
            for row in rows
        ],
        total=int(total),
    )
