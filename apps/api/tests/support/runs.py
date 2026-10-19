"""Totals of the lines one sync run stored."""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import SpendCostLine, SpendUsageLine


def cost_total(session: Session, run_id: int) -> Decimal:
    total = session.scalar(
        select(func.coalesce(func.sum(SpendCostLine.amount), 0)).where(
            SpendCostLine.sync_run_id == run_id
        )
    )
    return Decimal(total)


def usage_total(session: Session, run_id: int, column: str) -> Decimal:
    total = session.scalar(
        select(func.coalesce(func.sum(getattr(SpendUsageLine, column)), 0)).where(
            SpendUsageLine.sync_run_id == run_id
        )
    )
    return Decimal(total)
