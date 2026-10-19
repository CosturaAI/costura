"""Fetch Codex workspace and per-user usage, then apply configured credit prices."""

from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from costura import credit_prices
from costura.models import ProviderUser, SpendCostLine
from costura.providers.codex import PROVIDER
from costura.providers.codex.client import CodexAnalyticsClient, FetchedPage
from costura.providers.codex.normalize import (
    aggregate_cost_lines,
    aggregate_user_lines,
    cost_lines_from_payload,
    page_credits,
    user_lines_from_payload,
)
from costura.providers.lines import UsageLine
from costura.providers.records import UserRecord
from costura.providers.runs import SyncSummary, Target, run_report, write_records
from costura.providers.spend_lines import upsert_cost_lines, upsert_usage_lines

ENDPOINT_COST = "codex_workspace_usage"
ENDPOINT_COST_TOTAL = ENDPOINT_COST
ENDPOINT_USER = "codex_user_usage"
PRICE_PARAMS_KEY = "_costura_credit_prices"

type UserLine = UsageLine | UserRecord


def _workspace_id(session: Session, target: Target) -> str:
    account = credit_prices.codex_account(session, target.org_id, target.account_id)
    if not account.external_id:
        raise ValueError("Codex account has no workspace_id")
    return account.external_id


def _prices(session: Session, target: Target):
    return credit_prices.list_prices(session, target.org_id, target.account_id)


def _priced_pages(pages: Iterator[FetchedPage], prices) -> Iterator[FetchedPage]:
    schedule = [
        {
            "effective_from": row.effective_from.isoformat(),
            "price_per_credit": str(row.price_per_credit),
        }
        for row in prices
    ]
    for page in pages:
        yield replace(
            page,
            request_params={**page.request_params, PRICE_PARAMS_KEY: schedule},
        )


def run_cost_sync(
    session: Session,
    target: Target,
    client: CodexAnalyticsClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:
    workspace_id = _workspace_id(session, target)
    prices = _prices(session, target)
    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_COST,
        pages=lambda: _priced_pages(
            client.usage_pages(start, end, workspace=True),
            prices,
        ),
        start=start,
        end=end,
        normalize=lambda page: cost_lines_from_payload(
            page.payload,
            workspace_id=workspace_id,
            prices=prices,
        ),
        aggregate=aggregate_cost_lines,
        upsert=upsert_cost_lines,
        replaces=(SpendCostLine,),
    )


def run_user_sync(
    session: Session,
    target: Target,
    client: CodexAnalyticsClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:
    workspace_id = _workspace_id(session, target)
    prices = _prices(session, target)
    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_USER,
        pages=lambda: client.usage_pages(start, end),
        start=start,
        end=end,
        normalize=lambda page: user_lines_from_payload(
            page.payload,
            workspace_id=workspace_id,
            prices=prices,
        ),
        aggregate=aggregate_user_lines,
        upsert=_upsert_users,
    )


def _upsert_users(session: Session, target: Target, lines: Sequence[UserLine], run_id: int) -> int:
    usage = [line for line in lines if isinstance(line, UsageLine)]
    users = [line for line in lines if isinstance(line, UserRecord)]
    return upsert_usage_lines(session, target, usage, run_id) + write_records(
        session,
        ProviderUser,
        users,
        target,
        run_id,
        constraint="uq_provider_users_external_id",
        replace_columns=("email", "role", "added_at", "kind"),
    )


def page_amount_with_prices(
    payload: dict[str, Any],
    request_params: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
) -> Decimal:
    raw_schedule = request_params.get(PRICE_PARAMS_KEY, [])
    schedule = sorted(
        (
            date.fromisoformat(row["effective_from"]),
            Decimal(str(row["price_per_credit"])),
        )
        for row in raw_schedule
        if isinstance(row, dict)
        and isinstance(row.get("effective_from"), str)
        and row.get("price_per_credit") is not None
    )
    total = Decimal("0")
    for row in payload.get("data", []):
        if not isinstance(row, dict):
            continue
        value = row.get("start_time")
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        started = datetime.fromtimestamp(value, tz=UTC)
        if not window_start <= started < window_end:
            continue
        selected = next((price for day, price in reversed(schedule) if day <= started.date()), None)
        if selected is not None:
            total += page_credits({"data": [row]}, window_start, window_end) * selected
    return total


__all__ = [
    "ENDPOINT_COST",
    "ENDPOINT_COST_TOTAL",
    "ENDPOINT_USER",
    "page_amount_with_prices",
    "page_credits",
    "run_cost_sync",
    "run_user_sync",
]
