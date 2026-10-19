"""Fetch OpenAI Admin API reports, keep every raw page, and upsert normalized lines.

Cost, control-total and per-key reports feed billed spend and reconciliation. Completions feed
token usage; each non-completions usage family feeds activity lines. Run bookkeeping is shared
with the other providers through providers/runs.py.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from costura.models import SpendActivityLine, SpendCostLine, SpendUsageLine
from costura.providers.openai import PROVIDER
from costura.providers.openai.client import OpenAIAdminClient
from costura.providers.openai.normalize import (
    activity_lines_from_page,
    aggregate_activity_lines,
    aggregate_cost_lines,
    aggregate_usage_lines,
    bucket_day,
    cost_lines_from_page,
    result_amount,
    total_amounts,
    usage_lines_from_page,
)
from costura.providers.runs import SyncSummary, Target, run_report
from costura.providers.spend_lines import (
    upsert_activity_lines,
    upsert_cost_lines,
    upsert_usage_lines,
)

ENDPOINT_COST = "costs"
ENDPOINT_COST_TOTAL = "costs_total"
ENDPOINT_COST_BY_KEY = "costs_by_key"
ENDPOINT_USAGE = "usage_completions"
ACTIVITY_FAMILIES = (
    "images",
    "embeddings",
    "moderations",
    "audio_speeches",
    "audio_transcriptions",
    "vector_stores",
    "code_interpreter_sessions",
)
ACTIVITY_ENDPOINTS = tuple(f"usage_{family}" for family in ACTIVITY_FAMILIES)


def run_cost_sync(
    session: Session, target: Target, client: OpenAIAdminClient, start: datetime, end: datetime
) -> SyncSummary:
    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_COST,
        pages=lambda: client.costs_pages(start, end),
        start=start,
        end=end,
        normalize=lambda page: cost_lines_from_page(page.payload),
        aggregate=aggregate_cost_lines,
        upsert=upsert_cost_lines,
        replaces=(SpendCostLine,),
    )


def run_cost_total_sync(
    session: Session, target: Target, client: OpenAIAdminClient, start: datetime, end: datetime
) -> SyncSummary:
    """Control total: the costs report without `group_by`. Only raw pages are kept."""
    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_COST_TOTAL,
        pages=lambda: client.costs_total_pages(start, end),
        start=start,
        end=end,
        normalize=lambda page: total_amounts(page.payload),
        aggregate=list,
        upsert=lambda _session, _target, _amounts, _run_id: 0,
    )


def run_cost_by_key_sync(
    session: Session, target: Target, client: OpenAIAdminClient, start: datetime, end: datetime
) -> SyncSummary:
    """The provider's per-key money. Only raw pages are kept; `spend.reconcile` reads them
    for the per-key check (see `key_amounts`)."""
    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_COST_BY_KEY,
        pages=lambda: client.costs_by_key_pages(start, end),
        start=start,
        end=end,
        normalize=lambda page: total_amounts(page.payload),
        aggregate=list,
        upsert=lambda _session, _target, _amounts, _run_id: 0,
    )


def run_usage_sync(
    session: Session, target: Target, client: OpenAIAdminClient, start: datetime, end: datetime
) -> SyncSummary:
    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_USAGE,
        pages=lambda: client.usage_completions_pages(start, end),
        start=start,
        end=end,
        normalize=lambda page: usage_lines_from_page(page.payload),
        aggregate=aggregate_usage_lines,
        upsert=upsert_usage_lines,
        replaces=(SpendUsageLine,),
    )


def run_activity_sync(
    session: Session,
    target: Target,
    client: OpenAIAdminClient,
    start: datetime,
    end: datetime,
    *,
    family: str,
) -> SyncSummary:
    if family not in ACTIVITY_FAMILIES:
        raise ValueError(f"unknown OpenAI activity family: {family!r}")
    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=f"usage_{family}",
        pages=lambda: client.usage_family_pages(family, start, end),
        start=start,
        end=end,
        normalize=lambda page: activity_lines_from_page(page.payload, family),
        aggregate=aggregate_activity_lines,
        upsert=upsert_activity_lines,
        replaces=(SpendActivityLine,),
    )


def run_usage_images_sync(
    session: Session, target: Target, client: OpenAIAdminClient, start: datetime, end: datetime
) -> SyncSummary:
    return run_activity_sync(session, target, client, start, end, family="images")


def run_usage_embeddings_sync(
    session: Session, target: Target, client: OpenAIAdminClient, start: datetime, end: datetime
) -> SyncSummary:
    return run_activity_sync(session, target, client, start, end, family="embeddings")


def run_usage_moderations_sync(
    session: Session, target: Target, client: OpenAIAdminClient, start: datetime, end: datetime
) -> SyncSummary:
    return run_activity_sync(session, target, client, start, end, family="moderations")


def run_usage_audio_speeches_sync(
    session: Session, target: Target, client: OpenAIAdminClient, start: datetime, end: datetime
) -> SyncSummary:
    return run_activity_sync(session, target, client, start, end, family="audio_speeches")


def run_usage_audio_transcriptions_sync(
    session: Session, target: Target, client: OpenAIAdminClient, start: datetime, end: datetime
) -> SyncSummary:
    return run_activity_sync(session, target, client, start, end, family="audio_transcriptions")


def run_usage_vector_stores_sync(
    session: Session, target: Target, client: OpenAIAdminClient, start: datetime, end: datetime
) -> SyncSummary:
    return run_activity_sync(session, target, client, start, end, family="vector_stores")


def run_usage_code_interpreter_sessions_sync(
    session: Session, target: Target, client: OpenAIAdminClient, start: datetime, end: datetime
) -> SyncSummary:
    return run_activity_sync(
        session, target, client, start, end, family="code_interpreter_sessions"
    )


def page_amount(payload: dict[str, Any], window_start: datetime, window_end: datetime) -> Decimal:
    """Sum of `amount.value` over the results of one raw costs page whose bucket starts in
    `[window_start, window_end)`."""
    total = Decimal("0")
    for bucket in payload.get("data", []):
        if not isinstance(bucket, dict) or not isinstance(bucket.get("results"), list):
            continue
        day = bucket_day(bucket)
        if not window_start <= day < window_end:
            continue
        for result in bucket["results"]:
            if isinstance(result, dict):
                total += result_amount(result)[0]
    return total


def key_amounts(
    payload: dict[str, Any], window_start: datetime, window_end: datetime
) -> dict[str | None, Decimal]:
    """Per `api_key_id` sum of one raw `costs_by_key` page inside the window. Results with no
    key (money the provider does not tie to a key: images, storage) sum under `None`."""
    totals: dict[str | None, Decimal] = {}
    for bucket in payload.get("data", []):
        if not isinstance(bucket, dict) or not isinstance(bucket.get("results"), list):
            continue
        day = bucket_day(bucket)
        if not window_start <= day < window_end:
            continue
        for result in bucket["results"]:
            if not isinstance(result, dict):
                continue
            key = result.get("api_key_id")
            key_id = key if isinstance(key, str) and key else None
            totals[key_id] = totals.get(key_id, Decimal("0")) + result_amount(result)[0]
    return totals


__all__ = [
    "ACTIVITY_ENDPOINTS",
    "ACTIVITY_FAMILIES",
    "ENDPOINT_COST",
    "ENDPOINT_COST_BY_KEY",
    "ENDPOINT_COST_TOTAL",
    "ENDPOINT_USAGE",
    "key_amounts",
    "page_amount",
    "run_activity_sync",
    "run_cost_by_key_sync",
    "run_cost_sync",
    "run_cost_total_sync",
    "run_usage_audio_speeches_sync",
    "run_usage_audio_transcriptions_sync",
    "run_usage_code_interpreter_sessions_sync",
    "run_usage_embeddings_sync",
    "run_usage_images_sync",
    "run_usage_moderations_sync",
    "run_usage_sync",
    "run_usage_vector_stores_sync",
]
