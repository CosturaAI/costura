"""Fetch OpenRouter analytics for a window, keep every raw page, upsert normalized lines.

`analytics_cost` is one query grouped by key and model; each row becomes a cost line and a
usage line (see normalize.py). `analytics_total` is the same query without dimensions, kept
only as raw pages for the reconcile control total. Run bookkeeping is shared with Anthropic
through providers/runs.py.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from costura.models import SpendCostLine, SpendUsageLine
from costura.providers.lines import CostLine, UsageLine
from costura.providers.openrouter import PROVIDER
from costura.providers.openrouter.client import FetchedPage, OpenRouterManagementClient
from costura.providers.openrouter.normalize import (
    KeyDirectory,
    aggregate_cost_lines,
    aggregate_usage_lines,
    billed_amount,
    lines_from_rows,
    parse_day,
    total_amounts,
)
from costura.providers.runs import SyncSummary, Target, run_report
from costura.providers.spend_lines import upsert_cost_lines, upsert_usage_lines

ENDPOINT_COST = "analytics_cost"
ENDPOINT_COST_TOTAL = "analytics_total"

Line = CostLine | UsageLine


def run_cost_sync(
    session: Session,
    target: Target,
    client: OpenRouterManagementClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:
    """Cost and usage lines from one grouped analytics query. Key names are resolved against
    the current inventory, so `run_inventory_sync` should run first in a cycle."""
    directory = KeyDirectory.load(session, target.account_id)

    def normalize(page: FetchedPage) -> list[Line]:
        cost, usage = lines_from_rows(page.results, directory)
        return [*cost, *usage]

    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_COST,
        pages=lambda: client.analytics_cost_pages(start, end),
        start=start,
        end=end,
        normalize=normalize,
        aggregate=_aggregate,
        upsert=_upsert,
        replaces=(SpendCostLine, SpendUsageLine),
    )


def run_cost_total_sync(
    session: Session,
    target: Target,
    client: OpenRouterManagementClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:
    """Control total: the analytics query without dimensions. Only raw pages are kept."""
    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_COST_TOTAL,
        pages=lambda: client.analytics_total_pages(start, end),
        start=start,
        end=end,
        normalize=lambda page: total_amounts(page.results),
        aggregate=list,
        upsert=lambda _session, _target, _amounts, _run_id: 0,
    )


def page_amount(payload: dict[str, Any], window_start: datetime, window_end: datetime) -> Decimal:
    """Sum of the billed amount (`credits_usage`) over the rows of one raw analytics page that
    fall in the window."""
    total = Decimal("0")
    data = payload.get("data")
    rows = data.get("data", []) if isinstance(data, dict) else []
    for row in rows:
        day, _ = parse_day(row.get("date__day"))
        if window_start <= day < window_end:
            total += billed_amount(row)
    return total


def _aggregate(lines: list[Line]) -> list[Line]:
    cost = aggregate_cost_lines(line for line in lines if isinstance(line, CostLine))
    usage = aggregate_usage_lines(line for line in lines if isinstance(line, UsageLine))
    return [*cost, *usage]


def _upsert(session: Session, target: Target, lines: Sequence[Line], run_id: int) -> int:
    cost = [line for line in lines if isinstance(line, CostLine)]
    usage = [line for line in lines if isinstance(line, UsageLine)]
    return upsert_cost_lines(session, target, cost, run_id) + upsert_usage_lines(
        session, target, usage, run_id
    )


__all__ = [
    "ENDPOINT_COST",
    "ENDPOINT_COST_TOTAL",
    "page_amount",
    "run_cost_sync",
    "run_cost_total_sync",
]
