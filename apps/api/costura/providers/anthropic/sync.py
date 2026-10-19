"""Fetch Anthropic reports for a window, keep every raw page, upsert normalized lines.

One `provider_sync_runs` row per endpoint per call. Pages are committed as they arrive so a
failure halfway leaves the raw evidence in place; normalized lines are written in a single
transaction at the end with replace semantics.
"""

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from costura.models import SpendCostLine, SpendUsageLine
from costura.providers.anthropic import PROVIDER
from costura.providers.anthropic.client import AnthropicAdminClient, FetchedPage
from costura.providers.anthropic.normalize import cost_lines_from_payload, usage_lines_from_page
from costura.providers.lines import (
    aggregate_cost_lines,
    aggregate_usage_lines,
    parse_timestamp,
)
from costura.providers.runs import SyncSummary, Target, run_report
from costura.providers.spend_lines import upsert_cost_lines, upsert_usage_lines
from costura.spend.money import minor_to_major

ENDPOINT_COST = "cost_report"
ENDPOINT_COST_TOTAL = "cost_total"
ENDPOINT_USAGE = "usage_report_messages"


def run_cost_sync(
    session: Session,
    target: Target,
    client: AnthropicAdminClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:
    return _run(
        session,
        target,
        endpoint=ENDPOINT_COST,
        pages=lambda: client.cost_report_pages(start, end),
        start=start,
        end=end,
        normalize=lambda page: cost_lines_from_payload(page.payload),
        aggregate=aggregate_cost_lines,
        upsert=upsert_cost_lines,
        replaces=(SpendCostLine,),
    )


@dataclass(frozen=True)
class TotalBucket:
    """One ungrouped cost_report result: the organization's amount for one day."""

    amount: Decimal
    currency: str


def run_cost_total_sync(
    session: Session,
    target: Target,
    client: AnthropicAdminClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:
    """Control total: the cost report without `group_by[]`. Only the raw pages are kept; the
    reconcile check compares their sum with `spend_cost_lines`, so nothing is upserted."""
    return _run(
        session,
        target,
        endpoint=ENDPOINT_COST_TOTAL,
        pages=lambda: client.cost_total_pages(start, end),
        start=start,
        end=end,
        normalize=_total_buckets_from_page,
        aggregate=list,
        upsert=lambda _session, _target, _lines, _run_id: 0,
    )


def run_usage_sync(
    session: Session,
    target: Target,
    client: AnthropicAdminClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:
    return _run(
        session,
        target,
        endpoint=ENDPOINT_USAGE,
        pages=lambda: client.usage_report_pages(start, end),
        start=start,
        end=end,
        normalize=usage_lines_from_page,
        aggregate=aggregate_usage_lines,
        upsert=upsert_usage_lines,
        replaces=(SpendUsageLine,),
    )


def _run[LineT](
    session: Session,
    target: Target,
    *,
    endpoint: str,
    pages: Callable[[], Iterator[FetchedPage]],
    start: datetime,
    end: datetime,
    normalize: Callable[[FetchedPage], list[LineT]],
    aggregate: Callable[[list[LineT]], list[LineT]],
    upsert: Callable[[Session, Target, Sequence[LineT], int], int],
    replaces: Sequence[type[SpendCostLine] | type[SpendUsageLine]] = (),
) -> SyncSummary:
    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=endpoint,
        pages=pages,
        start=start,
        end=end,
        normalize=normalize,
        aggregate=aggregate,
        upsert=upsert,
        replaces=replaces,
    )


def page_amount(payload: dict[str, Any], window_start: datetime, window_end: datetime) -> Decimal:
    """Sum of the `amount` strings of one raw report page, restricted to buckets that start in
    `[window_start, window_end)`."""
    total = Decimal("0")
    for bucket in payload.get("data", []):
        bucket_start = parse_timestamp(bucket.get("starting_at"), field="starting_at")
        if not window_start <= bucket_start < window_end:
            continue
        for result in bucket.get("results", []):
            total += minor_to_major(result["amount"], result["currency"])
    return total


def _total_buckets_from_page(page: FetchedPage) -> list[TotalBucket]:
    return [
        TotalBucket(amount=minor_to_major(r["amount"], r["currency"]), currency=r["currency"])
        for r in page.results
    ]


__all__ = [
    "ENDPOINT_COST",
    "ENDPOINT_COST_TOTAL",
    "ENDPOINT_USAGE",
    "page_amount",
    "run_cost_sync",
    "run_cost_total_sync",
    "run_usage_sync",
]
