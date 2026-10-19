"""Replace-style upsert of normalized cost and usage lines, shared by every provider sync."""

from collections.abc import Sequence
from dataclasses import asdict

from sqlalchemy.orm import Session

from costura.models import SpendActivityLine, SpendCostLine, SpendUsageLine
from costura.providers.lines import ActivityLine, CostLine, UsageLine
from costura.providers.runs import Target
from costura.providers.upsert import upsert_rows
from costura.spend.money import to_storage

TOKEN_FIELDS = (
    "uncached_input_tokens",
    "cache_creation_5m_tokens",
    "cache_creation_1h_tokens",
    "cache_read_tokens",
    "output_tokens",
    "web_search_requests",
    "reasoning_tokens",
    "request_count",
)


def upsert_cost_lines(
    session: Session, target: Target, lines: Sequence[CostLine], run_id: int
) -> int:
    rows = []
    for line in lines:
        row = asdict(line)
        row["amount"] = to_storage(line.amount)
        row["list_amount"] = None if line.list_amount is None else to_storage(line.list_amount)
        row["organization_id"] = target.org_id
        row["provider_account_id"] = target.account_id
        row["sync_run_id"] = run_id
        rows.append(row)
    return upsert_rows(
        session,
        SpendCostLine,
        rows,
        constraint="uq_spend_cost_lines_key",
        replace_columns=("period_end", "amount", "list_amount", "currency", "raw_amount_minor"),
    )


def upsert_usage_lines(
    session: Session, target: Target, lines: Sequence[UsageLine], run_id: int
) -> int:
    rows = []
    for line in lines:
        row = asdict(line)
        row["amount"] = None if line.amount is None else to_storage(line.amount)
        row["byok_amount"] = None if line.byok_amount is None else to_storage(line.byok_amount)
        row["list_amount"] = None if line.list_amount is None else to_storage(line.list_amount)
        row["organization_id"] = target.org_id
        row["provider_account_id"] = target.account_id
        row["sync_run_id"] = run_id
        rows.append(row)
    return upsert_rows(
        session,
        SpendUsageLine,
        rows,
        constraint="uq_spend_usage_lines_key",
        replace_columns=(
            "period_end",
            *TOKEN_FIELDS,
            "amount",
            "currency",
            "byok_amount",
            "list_amount",
        ),
    )


def upsert_activity_lines(
    session: Session, target: Target, lines: Sequence[ActivityLine], run_id: int
) -> int:
    rows = []
    for line in lines:
        row = asdict(line)
        row["quantity"] = to_storage(line.quantity)
        row["organization_id"] = target.org_id
        row["provider_account_id"] = target.account_id
        row["sync_run_id"] = run_id
        rows.append(row)
    return upsert_rows(
        session,
        SpendActivityLine,
        rows,
        constraint="uq_spend_activity_lines_key",
        replace_columns=("period_end", "unit", "quantity", "request_count"),
    )
