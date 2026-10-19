"""The allocation strategies as pure functions over loaded cost buckets and usage rows.

`split_by_tokens` divides each bucket across its usage rows in proportion to the tokens of its
token type; `attribute_direct` and `attribute_claude_ai` take the cost the usage rows
already carry; `attribute_by_key` hands each bucket whole to the key the cost report
names. Every strategy records what it could not place as unallocated rows with a
reason, so allocated plus unallocated always equals the cost."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from costura.models.allocation import (
    ALLOCATION_METHOD_KEY_ATTRIBUTED,
    ALLOCATION_METHOD_PROVIDER_ATTRIBUTED,
    ALLOCATION_METHOD_TOKEN_SHARE,
)
from costura.spend.money import STORAGE_EXPONENT, split_proportionally, to_storage
from costura.spend.window import Window

COST_TYPE_TOKENS = "tokens"

COST_TYPE_WEB_SEARCH = "web_search"

# Cost report token_type -> spend_usage_lines column holding the share basis.
TOKEN_TYPE_COLUMNS: dict[str, str] = {
    "uncached_input_tokens": "uncached_input_tokens",
    "cache_read_input_tokens": "cache_read_tokens",
    "cache_creation.ephemeral_5m_input_tokens": "cache_creation_5m_tokens",
    "cache_creation.ephemeral_1h_input_tokens": "cache_creation_1h_tokens",
    "output_tokens": "output_tokens",
}


WEB_SEARCH_COLUMN = "web_search_requests"

REASONING_COLUMN = "reasoning_tokens"

REASON_NO_USAGE = "no_usage"

REASON_UNSUPPORTED_COST_TYPE = "unsupported_cost_type"

# A direct provider reported cost that it did not tie to any user.
REASON_NO_USER = "no_user"

# A key-attributed provider reported a bucket without a key and no usage row prices it.
REASON_NO_KEY = "no_key"


@dataclass(frozen=True)
class Bucket:
    period_start: datetime
    workspace_id: str | None
    cost_type: str
    model: str | None
    token_type: str | None
    service_tier: str | None
    context_window: str | None
    inference_geo: str | None
    api_key_id: str | None = None
    description: str | None = None

    @property
    def usage_key(self) -> tuple[Any, ...]:
        """Usage rows join on everything but `cost_type`, `token_type` and `api_key_id`; web
        search cost has no model or tier, so it joins on day and workspace only."""
        if self.cost_type == COST_TYPE_WEB_SEARCH:
            return (self.period_start, self.workspace_id)
        return (
            self.period_start,
            self.workspace_id,
            self.model,
            self.service_tier,
            self.context_window,
            self.inference_geo,
        )


@dataclass
class AllocationSummary:
    provider: str
    window: Window
    run_id: int
    currency: str | None = None
    buckets: int = 0
    cost_total: Decimal = Decimal("0")
    allocated_total: Decimal = Decimal("0")
    allocated_rows: int = 0
    unallocated_total: Decimal = Decimal("0")
    unallocated_by_reason: dict[str, Decimal] = field(default_factory=dict)
    unallocated_buckets: list[tuple[Bucket, Decimal, str]] = field(default_factory=list)
    unpriced_tokens: dict[tuple[str, str, str | None], int] = field(default_factory=dict)

    @property
    def balanced(self) -> bool:
        return self.allocated_total + self.unallocated_total == self.cost_total


@dataclass
class CostBucket:
    bucket: Bucket
    period_end: datetime
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class UsageRow:
    period_start: datetime
    workspace_id: str | None
    api_key_id: str | None
    account_id: str | None
    model: str
    service_tier: str
    context_window: str | None
    inference_geo: str | None
    counters: dict[str, int]
    amount: Decimal | None = None
    product: str | None = None

    @property
    def bucket_key(self) -> tuple[Any, ...]:
        return (
            self.period_start,
            self.workspace_id,
            self.model,
            self.service_tier,
            self.context_window,
            self.inference_geo,
        )


def _basis_column(bucket: Bucket) -> str | None:
    if bucket.cost_type == COST_TYPE_WEB_SEARCH:
        return WEB_SEARCH_COLUMN
    if bucket.cost_type == COST_TYPE_TOKENS and bucket.token_type in TOKEN_TYPE_COLUMNS:
        return TOKEN_TYPE_COLUMNS[bucket.token_type]
    return None


def split_by_tokens(
    cost_buckets: Sequence[CostBucket],
    usage_rows: Sequence[UsageRow],
    summary: AllocationSummary,
    run_id: int,
    provider: str,
) -> list[dict[str, Any]]:
    by_bucket: dict[tuple[Any, ...], list[UsageRow]] = {}
    by_day_workspace: dict[tuple[Any, ...], list[UsageRow]] = {}
    for row in usage_rows:
        by_bucket.setdefault(row.bucket_key, []).append(row)
        by_day_workspace.setdefault((row.period_start, row.workspace_id), []).append(row)

    summary.currency = _window_currency(cost_buckets)

    priced: set[tuple[Any, ...]] = set()
    rows: list[dict[str, Any]] = []
    for cost in cost_buckets:
        bucket = cost.bucket
        summary.buckets += 1
        summary.cost_total += cost.amount
        column = _basis_column(bucket)
        if column is None:
            rows.append(_unallocated_row(cost, run_id, provider, REASON_UNSUPPORTED_COST_TYPE))
            _count_unallocated(summary, cost, REASON_UNSUPPORTED_COST_TYPE)
            continue
        candidates = (
            by_day_workspace if bucket.cost_type == COST_TYPE_WEB_SEARCH else by_bucket
        ).get(bucket.usage_key, [])
        # Group by principal: one allocated row per (api_key_id, account_id) in the bucket.
        weights: dict[tuple[str | None, str | None], int] = {}
        for row in candidates:
            tokens = row.counters[column]
            if tokens > 0:
                key = (row.api_key_id, row.account_id)
                weights[key] = weights.get(key, 0) + tokens
        if not weights:
            rows.append(_unallocated_row(cost, run_id, provider, REASON_NO_USAGE))
            _count_unallocated(summary, cost, REASON_NO_USAGE)
            continue
        priced.add((bucket.usage_key, column))
        principals = list(weights.items())
        parts = split_proportionally(cost.amount, [tokens for _, tokens in principals])
        bucket_tokens = sum(weights.values())
        for (api_key_id, account_id), tokens in principals:
            amount = parts.pop(0)
            rows.append(
                _row(
                    cost,
                    run_id,
                    provider,
                    api_key_id=api_key_id,
                    account_id=account_id,
                    tokens=tokens,
                    bucket_tokens=bucket_tokens,
                    amount=amount,
                )
            )
            summary.allocated_total += amount
            summary.allocated_rows += 1

    for row in usage_rows:
        for token_type, column in TOKEN_TYPE_COLUMNS.items():
            tokens = row.counters[column]
            if tokens > 0 and (row.bucket_key, column) not in priced:
                key = (row.model, token_type, row.context_window)
                summary.unpriced_tokens[key] = summary.unpriced_tokens.get(key, 0) + tokens
    return rows


def attribute_direct(
    cost_buckets: Sequence[CostBucket],
    usage_rows: Sequence[UsageRow],
    summary: AllocationSummary,
    run_id: int,
    provider: str,
) -> list[dict[str, Any]]:
    """Copy provider-attributed amounts; keep positive unattributed residue as `no_user`."""
    by_bucket: dict[tuple[Any, ...], list[UsageRow]] = {}
    for row in usage_rows:
        by_bucket.setdefault(row.bucket_key, []).append(row)
    summary.currency = _window_currency(cost_buckets)

    rows: list[dict[str, Any]] = []
    for cost in cost_buckets:
        summary.buckets += 1
        summary.cost_total += cost.amount
        if cost.bucket.cost_type != COST_TYPE_TOKENS:
            rows.append(_unallocated_row(cost, run_id, provider, REASON_UNSUPPORTED_COST_TYPE))
            _count_unallocated(summary, cost, REASON_UNSUPPORTED_COST_TYPE)
            continue
        candidates = [r for r in by_bucket.get(cost.bucket.usage_key, []) if r.amount is not None]
        if not candidates:
            rows.append(_unallocated_row(cost, run_id, provider, REASON_NO_USER))
            _count_unallocated(summary, cost, REASON_NO_USER)
            continue
        principals = _direct_principals(candidates)
        residue = cost.amount - sum((amount for amount, _ in principals.values()), Decimal("0"))
        if residue < -STORAGE_EXPONENT:
            raise ValueError(
                f"provider-attributed usage exceeds its cost bucket by {-residue}; "
                f"maximum residue is {STORAGE_EXPONENT}"
            )
        largest = max(principals, key=lambda k: principals[k][0])
        bucket_tokens = sum(tokens for _, tokens in principals.values())
        for (api_key_id, account_id), (amount, tokens) in principals.items():
            if (api_key_id, account_id) == largest and abs(residue) <= STORAGE_EXPONENT:
                amount += residue
            if amount < 0:
                raise ValueError("provider-attributed residue would produce a negative amount")
            rows.append(
                _row(
                    cost,
                    run_id,
                    provider,
                    api_key_id=api_key_id,
                    account_id=account_id,
                    tokens=tokens,
                    bucket_tokens=bucket_tokens,
                    amount=amount,
                    method=ALLOCATION_METHOD_PROVIDER_ATTRIBUTED,
                )
            )
            summary.allocated_total += amount
            summary.allocated_rows += 1
        if residue > STORAGE_EXPONENT:
            remainder = _row(
                cost,
                run_id,
                provider,
                api_key_id=None,
                account_id=None,
                tokens=0,
                bucket_tokens=bucket_tokens,
                amount=residue,
                unallocated_reason=REASON_NO_USER,
                method=ALLOCATION_METHOD_PROVIDER_ATTRIBUTED,
            )
            rows.append(remainder)
            _count_unallocated(summary, cost, REASON_NO_USER, amount=residue)
    return rows


def _group_claude_ai(
    cost_buckets: Sequence[CostBucket],
    usage_rows: Sequence[UsageRow],
    summary: AllocationSummary,
) -> tuple[dict[tuple[Any, ...], list[CostBucket]], dict[tuple[Any, ...], list[UsageRow]]]:
    """Group organization costs and per-user lines by day, product and model."""
    grouped_cost: dict[tuple[Any, ...], list[CostBucket]] = {}
    for cost in cost_buckets:
        if cost.amount < 0:
            raise ValueError("Claude.ai organization costs must be non-negative")
        key = (cost.bucket.period_start, cost.bucket.description, cost.bucket.model)
        grouped_cost.setdefault(key, []).append(cost)
        summary.buckets += 1
        summary.cost_total += cost.amount

    grouped_usage: dict[tuple[Any, ...], list[UsageRow]] = {}
    for line in usage_rows:
        if line.amount is None:
            continue
        if line.amount < 0:
            raise ValueError("Claude.ai per-user costs must be non-negative")
        key = (line.period_start, line.product or "other", line.model)
        grouped_usage.setdefault(key, []).append(line)
    return grouped_cost, grouped_usage


def _claude_ai_demands(
    costs: Sequence[CostBucket],
    lines: Sequence[UsageRow],
) -> list[tuple[str | None, Decimal, int]]:
    """Per-user demand for one group, with the unattributed residue carried by a NULL account."""
    principals: dict[str, tuple[Decimal, int]] = {}
    for line in lines:
        if line.account_id is None:
            continue
        amount, tokens = principals.get(line.account_id, (Decimal("0"), 0))
        principals[line.account_id] = (
            amount + (line.amount or Decimal("0")),
            tokens + _token_count(line),
        )
    organization_amount = sum((cost.amount for cost in costs), Decimal("0"))
    attributed_amount = sum((amount for amount, _ in principals.values()), Decimal("0"))
    residue = organization_amount - attributed_amount
    if residue < -STORAGE_EXPONENT:
        raise ValueError(f"Claude.ai user-attributed cost exceeds organization cost by {-residue}")
    if residue < 0 and principals:
        largest = max(principals, key=lambda account: principals[account][0])
        amount, tokens = principals[largest]
        principals[largest] = (amount + residue, tokens)
        residue = Decimal("0")
    demands: list[tuple[str | None, Decimal, int]] = [
        (account_id, amount, tokens)
        for account_id, (amount, tokens) in sorted(principals.items())
        if amount > 0
    ]
    if residue > 0:
        demands.append((None, residue, 0))
    return demands


def attribute_claude_ai(
    cost_buckets: Sequence[CostBucket],
    usage_rows: Sequence[UsageRow],
    summary: AllocationSummary,
    run_id: int,
    provider: str,
) -> list[dict[str, Any]]:
    """Reconcile per-user product/model totals against detailed organization cost rows."""
    summary.currency = _window_currency(cost_buckets)
    grouped_cost, grouped_usage = _group_claude_ai(cost_buckets, usage_rows, summary)

    rows: list[dict[str, Any]] = []
    for key, costs in grouped_cost.items():
        demands = _claude_ai_demands(costs, grouped_usage.get(key, []))
        demand_index = 0
        demand_remaining = demands[0][1] if demands else Decimal("0")
        bucket_tokens = sum(tokens for _, _, tokens in demands)
        for cost in costs:
            capacity = cost.amount
            while capacity > 0:
                if demand_index >= len(demands):
                    raise ValueError("Claude.ai allocation exhausted user and remainder demand")
                account_id, _demand, tokens = demands[demand_index]
                amount = min(capacity, demand_remaining)
                unallocated = REASON_NO_USER if account_id is None else None
                rows.append(
                    _row(
                        cost,
                        run_id,
                        provider,
                        api_key_id=None,
                        account_id=account_id,
                        tokens=tokens,
                        bucket_tokens=bucket_tokens,
                        amount=amount,
                        unallocated_reason=unallocated,
                        method=ALLOCATION_METHOD_PROVIDER_ATTRIBUTED,
                    )
                )
                if unallocated is None:
                    summary.allocated_total += amount
                    summary.allocated_rows += 1
                else:
                    _count_unallocated(summary, cost, REASON_NO_USER, amount=amount)
                capacity -= amount
                demand_remaining -= amount
                if demand_remaining == 0:
                    demand_index += 1
                    if demand_index < len(demands):
                        demand_remaining = demands[demand_index][1]
    return rows


def attribute_by_key(
    cost_buckets: Sequence[CostBucket],
    usage_rows: Sequence[UsageRow],
    key_owners: dict[str, str],
    summary: AllocationSummary,
    run_id: int,
    provider: str,
) -> list[dict[str, Any]]:
    """Hand each bucket to the key the provider reported it under.

    The account is the usage rows' `account_id` for `(day, workspace, key)`: one account takes
    the bucket whole, several split it by their tokens of the bucket's token type (all tokens
    for a non-token line item), none falls back to the key's owner in the inventory. A bucket
    without a key is split by token share when the cost type allows it and is otherwise
    unallocated as `no_key`.
    """
    by_key: dict[tuple[Any, ...], list[UsageRow]] = {}
    for row in usage_rows:
        if row.api_key_id is not None:
            by_key.setdefault((row.period_start, row.workspace_id, row.api_key_id), []).append(row)
    summary.currency = _window_currency(cost_buckets)

    keyless = [cost for cost in cost_buckets if cost.bucket.api_key_id is None]
    rows = split_by_tokens(keyless, usage_rows, summary, run_id, provider) if keyless else []
    # `split_by_tokens` reports a bucket with no usage basis as unsupported; for this provider the
    # missing piece is the key, so the reason says so.
    for row in rows:
        if row["unallocated_reason"] is not None:
            row["unallocated_reason"] = REASON_NO_KEY
    if summary.unallocated_by_reason:
        keyless_total = sum(summary.unallocated_by_reason.values(), Decimal(0))
        summary.unallocated_by_reason = {REASON_NO_KEY: keyless_total}
    summary.unallocated_buckets = [
        (bucket, amount, REASON_NO_KEY) for bucket, amount, _ in summary.unallocated_buckets
    ]

    for cost in cost_buckets:
        bucket = cost.bucket
        if bucket.api_key_id is None:
            continue
        summary.buckets += 1
        summary.cost_total += cost.amount
        candidates = by_key.get((bucket.period_start, bucket.workspace_id, bucket.api_key_id), [])
        column = _basis_column(bucket)
        weights = _key_weights(candidates, column) or {
            _key_account(candidates, key_owners, bucket.api_key_id): 0
        }
        principals = list(weights.items())
        parts = (
            split_proportionally(cost.amount, [tokens for _, tokens in principals])
            if len(principals) > 1
            else [cost.amount]
        )
        bucket_tokens = sum(weights.values())
        for (account_id, tokens), amount in zip(principals, parts, strict=True):
            rows.append(
                _row(
                    cost,
                    run_id,
                    provider,
                    api_key_id=bucket.api_key_id,
                    account_id=account_id,
                    tokens=tokens,
                    bucket_tokens=bucket_tokens,
                    amount=amount,
                    method=ALLOCATION_METHOD_KEY_ATTRIBUTED,
                )
            )
            summary.allocated_total += amount
            summary.allocated_rows += 1
    return rows


def _window_currency(cost_buckets: Sequence[CostBucket]) -> str | None:
    currencies = {cost.currency for cost in cost_buckets}
    if len(currencies) > 1:
        raise ValueError(f"mixed currencies in window: {sorted(currencies)}")
    return currencies.pop() if currencies else None


def _direct_principals(
    candidates: Sequence[UsageRow],
) -> dict[tuple[str | None, str | None], tuple[Decimal, int]]:
    """Amount and tokens per `(api_key_id, account_id)` the provider attributed the bucket to."""
    principals: dict[tuple[str | None, str | None], tuple[Decimal, int]] = {}
    for row in candidates:
        key = (row.api_key_id, row.account_id)
        amount, tokens = principals.get(key, (Decimal("0"), 0))
        principals[key] = (amount + (row.amount or 0), tokens + _token_count(row))
    if any(amount < 0 for amount, _ in principals.values()):
        raise ValueError("provider-attributed amounts must be non-negative")
    return principals


def _key_weights(candidates: Sequence[UsageRow], column: str | None) -> dict[str | None, int]:
    weights: dict[str | None, int] = {}
    for row in candidates:
        tokens = row.counters[column] if column is not None else _token_count(row)
        if tokens > 0:
            weights[row.account_id] = weights.get(row.account_id, 0) + tokens
    return weights


def _key_account(
    candidates: Sequence[UsageRow], key_owners: dict[str, str], api_key_id: str
) -> str | None:
    """With no tokens to weigh, the bucket goes to the key's only account, else its owner."""
    accounts = {row.account_id for row in candidates if row.account_id is not None}
    return accounts.pop() if len(accounts) == 1 else key_owners.get(api_key_id)


def _token_count(row: UsageRow) -> int:
    return sum(count for name, count in row.counters.items() if name != WEB_SEARCH_COLUMN)


def _count_unallocated(
    summary: AllocationSummary,
    cost: CostBucket,
    reason: str,
    *,
    amount: Decimal | None = None,
) -> None:
    amount = cost.amount if amount is None else amount
    summary.unallocated_total += amount
    summary.unallocated_by_reason[reason] = (
        summary.unallocated_by_reason.get(reason, Decimal("0")) + amount
    )
    summary.unallocated_buckets.append((cost.bucket, amount, reason))


def _row(
    cost: CostBucket,
    run_id: int,
    provider: str,
    *,
    api_key_id: str | None,
    account_id: str | None,
    tokens: int,
    bucket_tokens: int,
    amount: Decimal,
    unallocated_reason: str | None = None,
    method: str = ALLOCATION_METHOD_TOKEN_SHARE,
) -> dict[str, Any]:
    bucket = cost.bucket
    return {
        "provider": provider,
        "period_start": bucket.period_start,
        "period_end": cost.period_end,
        "workspace_id": bucket.workspace_id,
        "description": bucket.description,
        "api_key_id": api_key_id,
        "account_id": account_id,
        "cost_type": bucket.cost_type,
        "model": bucket.model,
        "token_type": bucket.token_type,
        "service_tier": bucket.service_tier,
        "context_window": bucket.context_window,
        "inference_geo": bucket.inference_geo,
        "tokens": tokens,
        "bucket_tokens": bucket_tokens,
        "bucket_amount": to_storage(cost.amount),
        "amount": to_storage(amount),
        "currency": cost.currency,
        "method": method,
        "unallocated_reason": unallocated_reason,
        "allocation_run_id": run_id,
    }


def _unallocated_row(cost: CostBucket, run_id: int, provider: str, reason: str) -> dict[str, Any]:
    return _row(
        cost,
        run_id,
        provider,
        api_key_id=None,
        account_id=None,
        tokens=0,
        bucket_tokens=0,
        amount=cost.amount,
        unallocated_reason=reason,
    )
