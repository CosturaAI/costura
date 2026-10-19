"""Sync Claude.ai organization cost and per-user analytics."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from costura.models import SpendCostLine, SpendUsageLine
from costura.providers.claude_ai import PROVIDER
from costura.providers.claude_ai.client import ClaudeAiAnalyticsClient
from costura.providers.claude_ai.normalize import (
    TotalLine,
    aggregate_cost_lines,
    aggregate_usage_lines,
    cost_lines_from_payload,
    page_amount,
    total_lines_from_payload,
    user_lines_from_page,
)
from costura.providers.lines import CostLine
from costura.providers.runs import SyncSummary, Target, run_report
from costura.providers.spend_lines import upsert_cost_lines, upsert_usage_lines

ENDPOINT_COST = "analytics_cost_report"
ENDPOINT_COST_TOTAL = "analytics_cost_total"
ENDPOINT_USER = "analytics_user_reports"


def run_cost_sync(
    session: Session,
    target: Target,
    client: ClaudeAiAnalyticsClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:
    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_COST,
        pages=lambda: client.cost_report_pages(start, end),
        start=start,
        end=end,
        normalize=lambda page: cost_lines_from_payload(page.payload),
        aggregate=aggregate_cost_lines,
        upsert=upsert_cost_lines,
        replaces=(SpendCostLine,),
    )


def run_cost_total_sync(
    session: Session,
    target: Target,
    client: ClaudeAiAnalyticsClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:
    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_COST_TOTAL,
        pages=lambda: client.cost_total_pages(start, end),
        start=start,
        end=end,
        normalize=lambda page: total_lines_from_payload(page.payload),
        aggregate=list,
        upsert=_upsert_total_remainders,
    )


def run_user_sync(
    session: Session,
    target: Target,
    client: ClaudeAiAnalyticsClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:
    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_USER,
        pages=lambda: client.user_report_pages(start, end),
        start=start,
        end=end,
        normalize=user_lines_from_page,
        aggregate=aggregate_usage_lines,
        upsert=upsert_usage_lines,
        replaces=(SpendUsageLine,),
    )


def _upsert_total_remainders(
    session: Session, target: Target, totals: Sequence[TotalLine], run_id: int
) -> int:
    """Represent grouped-report omissions without duplicating its returned dimensions."""
    if not totals:
        return 0
    starts = [line.period_start for line in totals]
    session.execute(
        delete(SpendCostLine).where(
            SpendCostLine.organization_id == target.org_id,
            SpendCostLine.provider_account_id == target.account_id,
            SpendCostLine.provider == PROVIDER,
            SpendCostLine.period_start.in_(starts),
            SpendCostLine.cost_type == "org_remainder",
        )
    )
    remainders: list[CostLine] = []
    for total in totals:
        grouped_amount, grouped_list = session.execute(
            select(
                func.coalesce(func.sum(SpendCostLine.amount), 0),
                func.coalesce(func.sum(SpendCostLine.list_amount), 0),
            ).where(
                SpendCostLine.organization_id == target.org_id,
                SpendCostLine.provider_account_id == target.account_id,
                SpendCostLine.provider == PROVIDER,
                SpendCostLine.period_start == total.period_start,
                SpendCostLine.cost_type != "org_remainder",
            )
        ).one()
        amount = total.amount - Decimal(grouped_amount or 0)
        list_amount = total.list_amount - Decimal(grouped_list or 0)
        if amount < 0 or list_amount < 0:
            raise ValueError("grouped Claude.ai cost exceeds its organization control total")
        if amount == 0 and list_amount == 0:
            continue
        remainders.append(
            CostLine(
                period_start=total.period_start,
                period_end=total.period_end,
                workspace_id=None,
                description="other",
                cost_type="org_remainder",
                model=None,
                token_type=None,
                service_tier=None,
                context_window=None,
                inference_geo=None,
                amount=amount,
                list_amount=list_amount,
                currency=total.currency,
                raw_amount_minor=total.raw_amount_minor,
                provider=PROVIDER,
            )
        )
    return upsert_cost_lines(session, target, remainders, run_id)


def page_amount_for_reconcile(
    payload: dict[str, Any], window_start: datetime, window_end: datetime
) -> Decimal:
    return page_amount(payload, window_start, window_end)


__all__ = [
    "ENDPOINT_COST",
    "ENDPOINT_COST_TOTAL",
    "ENDPOINT_USER",
    "page_amount_for_reconcile",
    "run_cost_sync",
    "run_cost_total_sync",
    "run_user_sync",
]
