"""Allocate workspace-level cost buckets to the API keys and accounts that used them.

The cost report prices usage per bucket `(day, workspace, model, token_type, service_tier,
context_window, inference_geo)` but never names the credential. The usage report has the same
bucket plus `api_key_id` and `account_id`. Each bucket's real amount is split across its usage
rows proportionally to the tokens of that token type; the split is exact by construction, so
per-workspace sums equal the cost report. No list price is involved.

Providers whose usage rows already carry the key's cost (`ProviderSpec.attribution ==
"direct"`, OpenRouter) skip the split: each usage row's `amount` becomes the allocated amount,
method `provider_attributed`. Providers whose cost report names the key
(`"key_attributed"`, OpenAI `api_key_id`) hand each bucket to that key whole, whatever the
line item; the account is the key's user in the usage rows of the day, else the key's owner in
the inventory. The balance check against the cost lines is the same for all three.

The strategies are pure functions in `allocation_split`; this module loads their inputs, picks
one per provider and replaces the window in one transaction.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, insert, literal, select
from sqlalchemy.orm import Session

from costura import accounts
from costura.models import (
    ProviderApiKey,
    ProviderSyncRun,
    SpendAllocatedLine,
    SpendCostLine,
    SpendUsageLine,
)
from costura.models.allocation import (
    ALLOCATION_ENDPOINT,
)
from costura.providers.http import stored_exception_text
from costura.providers.registry import get_spec
from costura.spend.allocation_split import (
    REASONING_COLUMN,
    TOKEN_TYPE_COLUMNS,
    WEB_SEARCH_COLUMN,
    AllocationSummary,
    Bucket,
    CostBucket,
    UsageRow,
    attribute_by_key,
    attribute_claude_ai,
    attribute_direct,
    split_by_tokens,
)
from costura.spend.window import Window


def run_allocation(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    *,
    account_id: int | None = None,
) -> AllocationSummary:
    """Replace the allocation of `window` for one account of `provider` and record the run.
    Without `account_id`, every account of the provider is allocated in turn and the summary
    adds them up."""
    if account_id is None:
        return _run_for_accounts(session, org_id, provider, window)
    run = ProviderSyncRun(
        organization_id=org_id,
        provider=provider,
        provider_account_id=account_id,
        endpoint=ALLOCATION_ENDPOINT,
        window_start=window.start,
        window_end=window.end,
    )
    session.add(run)
    session.commit()
    summary = AllocationSummary(provider=provider, window=window, run_id=run.id)
    try:
        cost_buckets = _load_cost_buckets(session, org_id, provider, window, account_id)
        usage_rows = _load_usage_rows(session, org_id, provider, window, account_id)
        attribution = get_spec(provider).attribution
        if attribution == "direct":
            rows = (
                attribute_claude_ai(cost_buckets, usage_rows, summary, run.id, provider)
                if get_spec(provider).pooled_seats
                else attribute_direct(cost_buckets, usage_rows, summary, run.id, provider)
            )
        elif attribution == "key_attributed":
            owners = _load_key_owners(session, org_id, provider, account_id)
            rows = attribute_by_key(cost_buckets, usage_rows, owners, summary, run.id, provider)
        else:
            rows = split_by_tokens(cost_buckets, usage_rows, summary, run.id, provider)
        for row in rows:
            row["organization_id"] = org_id
            row["provider_account_id"] = account_id
        if not summary.balanced:
            raise ValueError(
                "allocation does not balance before replacement: "
                f"cost={summary.cost_total} allocated={summary.allocated_total} "
                f"unallocated={summary.unallocated_total}"
            )
        session.execute(
            delete(SpendAllocatedLine).where(
                SpendAllocatedLine.organization_id == org_id,
                SpendAllocatedLine.provider == provider,
                SpendAllocatedLine.provider_account_id == account_id,
                SpendAllocatedLine.period_start >= window.start,
                SpendAllocatedLine.period_start < window.end,
            )
        )
        if rows:
            session.execute(insert(SpendAllocatedLine), rows)
        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        run.raw_results = summary.buckets
        run.rows_upserted = summary.allocated_rows
        session.commit()
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.finished_at = datetime.now(UTC)
        run.error = stored_exception_text(exc)
        session.commit()
        raise
    return summary


def _run_for_accounts(
    session: Session, org_id: int, provider: str, window: Window
) -> AllocationSummary:
    ids = [a.id for a in accounts.list_accounts(session, org_id, provider)]
    if not ids:
        ids = [accounts.ensure_default_account(session, org_id, provider).id]
        session.commit()
    summaries = [run_allocation(session, org_id, provider, window, account_id=i) for i in ids]
    if len(summaries) == 1:
        return summaries[0]
    total = AllocationSummary(provider=provider, window=window, run_id=summaries[-1].run_id)
    currencies = {s.currency for s in summaries if s.currency is not None}
    total.currency = currencies.pop() if len(currencies) == 1 else None
    for s in summaries:
        total.buckets += s.buckets
        total.cost_total += s.cost_total
        total.allocated_total += s.allocated_total
        total.allocated_rows += s.allocated_rows
        total.unallocated_total += s.unallocated_total
        for reason, amount in s.unallocated_by_reason.items():
            total.unallocated_by_reason[reason] = (
                total.unallocated_by_reason.get(reason, Decimal("0")) + amount
            )
        total.unallocated_buckets.extend(s.unallocated_buckets)
        for key, tokens in s.unpriced_tokens.items():
            total.unpriced_tokens[key] = total.unpriced_tokens.get(key, 0) + tokens
    return total


def _load_cost_buckets(
    session: Session, org_id: int, provider: str, window: Window, account_id: int
) -> list[CostBucket]:
    description = (
        SpendCostLine.description
        if get_spec(provider).pooled_seats
        else literal(None, type_=SpendCostLine.description.type)
    ).label("description")
    dims = (
        SpendCostLine.period_start,
        SpendCostLine.workspace_id,
        description,
        SpendCostLine.cost_type,
        SpendCostLine.model,
        SpendCostLine.token_type,
        SpendCostLine.service_tier,
        SpendCostLine.context_window,
        SpendCostLine.inference_geo,
        SpendCostLine.api_key_id,
        SpendCostLine.currency,
    )
    rows = session.execute(
        select(*dims, func.max(SpendCostLine.period_end), func.sum(SpendCostLine.amount))
        .where(
            SpendCostLine.organization_id == org_id,
            SpendCostLine.provider == provider,
            SpendCostLine.provider_account_id == account_id,
            SpendCostLine.period_start >= window.start,
            SpendCostLine.period_start < window.end,
        )
        .group_by(*dims)
        .order_by(*dims)
    ).all()
    return [
        CostBucket(
            bucket=Bucket(
                period_start=row[0],
                workspace_id=row[1],
                description=row[2],
                cost_type=row[3],
                model=row[4],
                token_type=row[5],
                service_tier=row[6],
                context_window=row[7],
                inference_geo=row[8],
                api_key_id=row[9],
            ),
            currency=row[10],
            period_end=row[11],
            amount=Decimal(row[12]),
        )
        for row in rows
    ]


def _load_key_owners(
    session: Session, org_id: int, provider: str, account_id: int
) -> dict[str, str]:
    """`api_key_id -> principal_external_id` from the inventory, for buckets whose key made
    no completions request on the day (web search, embeddings, images)."""
    rows = session.execute(
        select(ProviderApiKey.external_id, ProviderApiKey.principal_external_id).where(
            ProviderApiKey.organization_id == org_id,
            ProviderApiKey.provider == provider,
            ProviderApiKey.provider_account_id == account_id,
            ProviderApiKey.principal_external_id.is_not(None),
        )
    ).all()
    return {external_id: principal for external_id, principal in rows if principal is not None}


def _load_usage_rows(
    session: Session, org_id: int, provider: str, window: Window, account_id: int
) -> list[UsageRow]:
    counters = (*TOKEN_TYPE_COLUMNS.values(), WEB_SEARCH_COLUMN, REASONING_COLUMN)
    lines = session.scalars(
        select(SpendUsageLine).where(
            SpendUsageLine.organization_id == org_id,
            SpendUsageLine.provider == provider,
            SpendUsageLine.provider_account_id == account_id,
            SpendUsageLine.period_start >= window.start,
            SpendUsageLine.period_start < window.end,
        )
    ).all()
    return [
        UsageRow(
            period_start=line.period_start,
            workspace_id=line.workspace_id,
            api_key_id=line.api_key_id,
            account_id=line.account_id,
            model=line.model,
            service_tier=line.service_tier,
            context_window=line.context_window,
            inference_geo=line.inference_geo,
            product=line.product,
            counters={name: getattr(line, name) for name in counters},
            amount=None if line.amount is None else Decimal(line.amount),
        )
        for line in lines
    ]
