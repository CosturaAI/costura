"""The allocation strategies without a database: whatever a strategy places or leaves
unallocated, allocated plus unallocated equals the cost to the last stored decimal."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from costura.spend.allocation_split import (
    COST_TYPE_TOKENS,
    REASON_NO_KEY,
    REASON_NO_USAGE,
    REASON_NO_USER,
    REASON_UNSUPPORTED_COST_TYPE,
    REASONING_COLUMN,
    TOKEN_TYPE_COLUMNS,
    WEB_SEARCH_COLUMN,
    AllocationSummary,
    Bucket,
    CostBucket,
    UsageRow,
    attribute_by_key,
    attribute_direct,
    split_by_tokens,
)
from costura.spend.window import Window

DAY = datetime(2026, 8, 3, tzinfo=UTC)
WINDOW = Window(start=DAY, end=DAY + timedelta(days=1))
RUN_ID = 7


def summary() -> AllocationSummary:
    return AllocationSummary(provider="anthropic", window=WINDOW, run_id=RUN_ID)


def cost(
    amount: str,
    *,
    token_type: str | None = "output_tokens",
    cost_type: str = COST_TYPE_TOKENS,
    api_key_id: str | None = None,
    currency: str = "USD",
) -> CostBucket:
    bucket = Bucket(
        period_start=DAY,
        workspace_id="wrk",
        cost_type=cost_type,
        model="claude-sonnet-4",
        token_type=token_type,
        service_tier="standard",
        context_window="0-200k",
        inference_geo=None,
        api_key_id=api_key_id,
    )
    return CostBucket(
        bucket=bucket, period_end=WINDOW.end, amount=Decimal(amount), currency=currency
    )


def usage(
    api_key_id: str | None,
    account_id: str | None = None,
    *,
    output_tokens: int = 0,
    amount: str | None = None,
) -> UsageRow:
    counters = {column: 0 for column in TOKEN_TYPE_COLUMNS.values()}
    counters[WEB_SEARCH_COLUMN] = 0
    counters[REASONING_COLUMN] = 0
    counters["output_tokens"] = output_tokens
    return UsageRow(
        period_start=DAY,
        workspace_id="wrk",
        api_key_id=api_key_id,
        account_id=account_id,
        model="claude-sonnet-4",
        service_tier="standard",
        context_window="0-200k",
        inference_geo=None,
        counters=counters,
        amount=None if amount is None else Decimal(amount),
    )


def placed(rows: list[dict]) -> Decimal:
    return sum((Decimal(row["amount"]) for row in rows), Decimal("0"))


def test_token_split_balances_exactly_when_the_shares_do_not_divide() -> None:
    result = summary()
    rows = split_by_tokens(
        [cost("0.10")],
        [usage("k1", output_tokens=1), usage("k2", output_tokens=1), usage("k3", output_tokens=1)],
        result,
        RUN_ID,
        "anthropic",
    )
    assert len(rows) == 3
    assert placed(rows) == Decimal("0.10")
    assert result.balanced
    assert result.allocated_total == Decimal("0.10")
    assert result.unallocated_total == 0


def test_buckets_without_a_basis_stay_unallocated_and_the_run_still_balances() -> None:
    result = summary()
    rows = split_by_tokens(
        [cost("2.50"), cost("1.25", token_type=None, cost_type="code_execution")],
        [],
        result,
        RUN_ID,
        "anthropic",
    )
    assert placed(rows) == Decimal("3.75")
    assert result.unallocated_by_reason == {
        REASON_NO_USAGE: Decimal("2.50"),
        REASON_UNSUPPORTED_COST_TYPE: Decimal("1.25"),
    }
    assert result.balanced


def test_mixed_currencies_in_one_window_are_refused() -> None:
    with pytest.raises(ValueError, match="mixed currencies"):
        split_by_tokens([cost("1"), cost("1", currency="EUR")], [], summary(), RUN_ID, "anthropic")


def test_direct_attribution_keeps_unattributed_residue_as_no_user() -> None:
    result = summary()
    rows = attribute_direct(
        [cost("5.00")],
        [usage(None, "acct-1", output_tokens=10, amount="3.00")],
        result,
        RUN_ID,
        "openrouter",
    )
    assert placed(rows) == Decimal("5.00")
    assert result.allocated_total == Decimal("3.00")
    assert result.unallocated_by_reason == {REASON_NO_USER: Decimal("2.00")}
    assert result.balanced


def test_direct_attribution_refuses_usage_above_its_bucket() -> None:
    with pytest.raises(ValueError, match="exceeds its cost bucket"):
        attribute_direct(
            [cost("1.00")],
            [usage(None, "acct-1", output_tokens=1, amount="1.50")],
            summary(),
            RUN_ID,
            "openrouter",
        )


def test_key_attribution_falls_back_to_the_owner_and_names_keyless_buckets() -> None:
    result = summary()
    rows = attribute_by_key(
        [cost("4.00", api_key_id="key-a"), cost("1.00")],
        [],
        {"key-a": "owner@example.com"},
        result,
        RUN_ID,
        "openai",
    )
    keyed = [row for row in rows if row["api_key_id"] == "key-a"]
    assert [(row["account_id"], Decimal(row["amount"])) for row in keyed] == [
        ("owner@example.com", Decimal("4.00"))
    ]
    assert result.unallocated_by_reason == {REASON_NO_KEY: Decimal("1.00")}
    assert placed(rows) == Decimal("5.00")
    assert result.balanced
