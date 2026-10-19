"""Synthetic daily spend for the anomaly, projection and budget tests.

`seed_days` writes one cost line per (day, workspace, model), one allocated line and one usage
line per (day, workspace, model, principal) with the amounts a plan dictates, under one
succeeded sync run each, so the series loaders see the same shape the sync and allocation
produce. A principal is an API key id, or `oauth(user_id)` for usage made with a Claude Code
login (no key, `account_id` set).

Token counters are derived from the money at a blended per-million rate, so the token mix and
the cache-read share on the overview hold figures instead of an empty state.
"""

import hashlib
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.orm import Session

from costura import accounts
from costura.models import ProviderSyncRun, SpendAllocatedLine, SpendCostLine, SpendUsageLine
from costura.spend.usage import TOKEN_COLUMNS

# (workspace_id, model, principal, amount) for one day.
Line = tuple[str | None, str, str, Decimal]
DayPlan = Callable[[date], Iterable[Line]]

# Blended USD per million tokens; the seed needs a plausible ratio between money and tokens,
# not a price sheet. Models the table does not name use `DEFAULT_RATE`.
RATES: dict[str, Decimal] = {
    "claude-opus-4-1": Decimal("30"),
    "claude-sonnet-4-5": Decimal("7"),
    "claude-sonnet-4": Decimal("6"),
    "claude-haiku-3-5": Decimal("1"),
    "openai/gpt-5.2": Decimal("5"),
    "x-ai/grok-4.6": Decimal("3"),
}
DEFAULT_RATE = Decimal("5")
# Of every token, roughly a fifth is generated; of the input, a tenth writes the cache.
OUTPUT_RATIO = Decimal("0.2")
CACHE_WRITE_RATIO = Decimal("0.1")
# One request per this many tokens, so the request counters grow with the spend.
TOKENS_PER_REQUEST = 4000

OAUTH_PREFIX = "oauth:"


def oauth(user_id: str) -> str:
    """The principal string of a plan line for usage made with `user_id`'s own login."""
    return f"{OAUTH_PREFIX}{user_id}"


def principal_columns(principal: str) -> tuple[str | None, str | None]:
    """`(api_key_id, account_id)` for a plan line's principal."""
    if principal.startswith(OAUTH_PREFIX):
        return None, principal.removeprefix(OAUTH_PREFIX)
    return principal, None


def cache_read_share(principal: str) -> Decimal:
    """0.30 to 0.70, fixed per principal: a key that caches well keeps caching well, so the
    savings lead the overview reads stays the same between imports."""
    digest = hashlib.sha256(principal.encode()).digest()
    return Decimal("0.30") + Decimal(digest[0] % 9) * Decimal("0.05")


def token_mix(model: str, principal: str, amount: Decimal) -> dict[str, int]:
    """Token counters that the per-million rate of `model` prices back to about `amount`."""
    rate = RATES.get(model, DEFAULT_RATE)
    total = int(amount / rate * 1_000_000)
    if total <= 0:
        return dict.fromkeys(TOKEN_COLUMNS, 0)
    output = int(total * OUTPUT_RATIO)
    input_tokens = total - output
    cache_read = int(input_tokens * cache_read_share(principal))
    cache_write = int(input_tokens * CACHE_WRITE_RATIO)
    return {
        "uncached_input_tokens": input_tokens - cache_read - cache_write,
        "cache_creation_5m_tokens": cache_write,
        "cache_creation_1h_tokens": 0,
        "cache_read_tokens": cache_read,
        "output_tokens": output,
        "reasoning_tokens": 0,
    }


def seed_days(
    session: Session, org_id: int, provider: str, start: date, end: date, plan: DayPlan
) -> None:
    """Write cost, usage and allocated lines for every day in `[start, end)` per `plan(day)`.
    The runs cover the whole months the days fall in, as the scheduler's do, so a month that
    ends after `end` (the current one) still counts as allocated. Usage lines of the window are
    replaced, since their grain is unique per day and a reseed would collide with itself. The
    rows land in the provider's default account (seeds know no console)."""
    provider_account_id = seed_account(session, org_id, provider)
    run_start, run_end = month_span(start, end)
    cost_run = sync_run(session, org_id, provider, "cost_report", run_start, run_end)
    usage_run = sync_run(session, org_id, provider, "usage_report_messages", run_start, run_end)
    alloc_run = sync_run(session, org_id, provider, "allocation", run_start, run_end)
    session.execute(
        delete(SpendUsageLine).where(
            SpendUsageLine.organization_id == org_id,
            SpendUsageLine.provider == provider,
            SpendUsageLine.provider_account_id == provider_account_id,
            SpendUsageLine.period_start >= datetime(start.year, start.month, start.day, tzinfo=UTC),
            SpendUsageLine.period_start < datetime(end.year, end.month, end.day, tzinfo=UTC),
        )
    )
    day = start
    while day < end:
        period_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        period_end = period_start + timedelta(days=1)
        by_bucket: dict[tuple[str | None, str], Decimal] = {}
        # The usage grain is unique per day, so plan lines that share it are one row.
        by_grain: dict[tuple[str | None, str | None, str | None, str], tuple[Decimal, str]] = {}
        for workspace_id, model, principal, amount in plan(day):
            api_key_id, account_id = principal_columns(principal)
            bucket = (workspace_id, model)
            by_bucket[bucket] = by_bucket.get(bucket, Decimal("0")) + amount
            grain = (workspace_id, api_key_id, account_id, model)
            seen, _ = by_grain.get(grain, (Decimal("0"), principal))
            by_grain[grain] = (seen + amount, principal)
            tokens = token_mix(model, principal, amount)
            session.add(
                SpendAllocatedLine(
                    organization_id=org_id,
                    provider=provider,
                    provider_account_id=provider_account_id,
                    period_start=period_start,
                    period_end=period_end,
                    workspace_id=workspace_id,
                    api_key_id=api_key_id,
                    account_id=account_id,
                    cost_type="tokens",
                    model=model,
                    token_type="uncached_input_tokens",
                    service_tier="standard",
                    context_window=None,
                    inference_geo=None,
                    tokens=tokens["uncached_input_tokens"],
                    bucket_tokens=tokens["uncached_input_tokens"],
                    bucket_amount=amount,
                    amount=amount,
                    currency="USD",
                    method="token_share",
                    allocation_run_id=alloc_run.id,
                )
            )
        for (workspace_id, api_key_id, account_id, model), (amount, principal) in by_grain.items():
            tokens = token_mix(model, principal, amount)
            session.add(
                SpendUsageLine(
                    organization_id=org_id,
                    provider=provider,
                    provider_account_id=provider_account_id,
                    period_start=period_start,
                    period_end=period_end,
                    workspace_id=workspace_id,
                    api_key_id=api_key_id,
                    account_id=account_id,
                    model=model,
                    service_tier="standard",
                    context_window=None,
                    inference_geo=None,
                    web_search_requests=0,
                    request_count=max(1, sum(tokens.values()) // TOKENS_PER_REQUEST),
                    sync_run_id=usage_run.id,
                    **tokens,
                )
            )
        for (workspace_id, model), amount in by_bucket.items():
            session.add(
                SpendCostLine(
                    organization_id=org_id,
                    provider=provider,
                    provider_account_id=provider_account_id,
                    period_start=period_start,
                    period_end=period_end,
                    workspace_id=workspace_id,
                    description=f"{model} tokens",
                    cost_type="tokens",
                    model=model,
                    token_type="uncached_input_tokens",
                    service_tier="standard",
                    amount=amount,
                    currency="USD",
                    raw_amount_minor=str(int(amount * 100)),
                    sync_run_id=cost_run.id,
                )
            )
        day += timedelta(days=1)
    session.commit()


def month_span(start: date, end: date) -> tuple[date, date]:
    """The first of `start`'s month and the first of the month after the last day in
    `[start, end)`."""
    last = end - timedelta(days=1)
    following = (last.replace(day=1) + timedelta(days=32)).replace(day=1)
    return start.replace(day=1), following


def seed_account(session: Session, org_id: int, provider: str) -> int:
    """The account seeded rows belong to: the provider's default account, created when the
    organization has none."""

    account = accounts.ensure_default_account(session, org_id, provider)
    session.flush()
    return account.id


def sync_run(
    session: Session, org_id: int, provider: str, endpoint: str, start: date, end: date
) -> ProviderSyncRun:
    """A succeeded `provider_sync_runs` row over `[start, end)` for rows to reference, in the
    provider's default account."""
    run = ProviderSyncRun(
        organization_id=org_id,
        provider=provider,
        provider_account_id=seed_account(session, org_id, provider),
        endpoint=endpoint,
        window_start=datetime(start.year, start.month, start.day, tzinfo=UTC),
        window_end=datetime(end.year, end.month, end.day, tzinfo=UTC),
        status="succeeded",
        finished_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    return run
