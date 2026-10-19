"""Token totals and allocated dollars for a window, grouped by api key, account, creator,
workspace or model, with inventory names.

Dollars come from `spend_allocated_lines` (see `spend.allocate`); when no allocation covers the
window the USD columns are None and the report is tokens only.

`movers` compares two windows of the same report and ranks the rows by how much money moved
between them, which is the question the overview asks first.

The `person` dimension folds direct login usage and qualifying Anthropic Claude Code keys
under one e-mail; application keys and accounts the inventory cannot
name stay provider-scoped.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.errors import InvalidInput
from costura.models import SpendAllocatedLine, SpendCostLine, SpendUsageLine
from costura.providers.registry import PROVIDERS, get_spec
from costura.spend import SERIES_DIMENSIONS, USAGE_DIMENSIONS
from costura.spend.allocation_check import allocation_covers
from costura.spend.dimensions import (
    PRINCIPAL_DIMENSIONS,
    PYTHON_FILTER_DIMENSIONS,
    UNALLOCATED_KEY,
    GroupKey,
    group_details,
    group_key,
    group_label,
    group_person,
)
from costura.spend.filters import (
    ClauseFilters,
    Filters,
    derived_matches,
    exact_filter,
    line_where,
    token_type_matches,
    validate_filters,
)
from costura.spend.inventory import (
    InventoryResolver,
)
from costura.spend.money import to_percent
from costura.spend.sql import utc_day
from costura.spend.taxonomy import (
    TOKEN_TYPE,
    token_type_label,
)
from costura.spend.window import Window

TOKEN_COLUMNS = (
    "uncached_input_tokens",
    "cache_creation_5m_tokens",
    "cache_creation_1h_tokens",
    "cache_read_tokens",
    "output_tokens",
    "reasoning_tokens",
)


@dataclass
class UsageRow:
    key: str | None
    label: str
    tokens: dict[str, int]
    web_search_requests: int
    amount: Decimal | None = None
    share: Decimal | None = None
    details: dict[str, str] = field(default_factory=dict)
    # Requests counted by the provider's usage report; 0 where the report has none.
    request_count: int = 0
    # The provider every line of the row came from; None when the row spans providers
    # (only possible for sentinel rows such as unallocated cost under the `all` scope).
    provider: str | None = None
    # BYOK inference billed by another provider, never part of `amount`; None when no usage
    # line of the row reports it.
    byok_amount: Decimal | None = None
    # The e-mail identity of the row's account when the inventory knows it (account, creator
    # and person rows), so a table can link to the person across providers.
    person: str | None = None
    # The provider account every line of the row came from, and its label, so a table can
    # badge the row "Provider - Account"; None when the row spans accounts.
    provider_account_id: int | None = None
    provider_account_label: str | None = None

    @property
    def total_tokens(self) -> int:
        return sum(self.tokens.values())


@dataclass
class UsageReport:
    dimension: str
    rows: list[UsageRow]
    allocated: bool
    cost_total: Decimal | None = None


def usage_report(
    session: Session,
    *,
    org_id: int,
    provider: str,
    window: Window,
    dimension: str,
    top: int | None = None,
    filters: Filters | None = None,
    resolver: InventoryResolver | None = None,
    allocated: bool | None = None,
) -> UsageReport:
    """`resolver` and `allocated` let a caller that reports several dimensions of one window
    (the anomaly evidence) load the inventory and the allocation decision once."""
    if dimension not in USAGE_DIMENSIONS:
        raise InvalidInput(f"unknown dimension {dimension!r}; expected one of {USAGE_DIMENSIONS}")
    applied = validate_filters(filters)
    line_filters = {
        key: value for key, value in applied.items() if key not in PYTHON_FILTER_DIMENSIONS
    }
    resolver = resolver or InventoryResolver(session, org_id, provider)
    groups: dict[GroupKey, _Group] = {}
    for line in _usage_groups(session, org_id, provider, window, line_filters, resolver):
        if _matches(line, applied, resolver, include_token_type=False):
            _add_usage(groups, line, dimension, applied, resolver)

    allocation_scope = (
        exact_filter(applied, "provider", provider) if provider == "all" else provider
    )
    if allocated is None:
        allocated = allocation_covers(session, org_id, allocation_scope, window)
    cost_total = Decimal("0")
    if allocated:
        for line in _allocated_groups(session, org_id, provider, window, line_filters, resolver):
            label = token_type_label(line.token_type)
            if not _matches(line, applied, resolver, token_type=label):
                continue
            key = (
                (line.provider, label)
                if dimension == TOKEN_TYPE
                else _cost_key(resolver, dimension, line)
            )
            amount = Decimal(line.amount)
            cost_total += amount
            group = groups.setdefault(key, _Group())
            group.providers.add(line.provider)
            group.accounts.add(line.provider_account_id)
            group.amount += amount

    rows = [
        _usage_row(resolver, dimension, key, group, allocated, cost_total)
        for key, group in groups.items()
    ]
    rows.sort(key=lambda r: (-(r.amount or 0), -r.total_tokens, r.label))
    if top is not None:
        rows = rows[:top]
    return UsageReport(
        dimension=dimension,
        rows=rows,
        allocated=allocated,
        cost_total=cost_total if allocated else None,
    )


def _matches(
    line: Any, applied: ClauseFilters, resolver: InventoryResolver, **options: Any
) -> bool:
    return derived_matches(
        line.provider,
        line.api_key_id,
        line.account_id,
        line.workspace_id,
        line.model,
        line.provider_account_id,
        applied,
        resolver,
        **options,
    )


def _entity_key(resolver: InventoryResolver, dimension: str, line: Any) -> GroupKey:
    return group_key(
        resolver,
        dimension,
        line.provider,
        line.api_key_id,
        line.account_id,
        line.workspace_id,
        line.model,
        line.provider_account_id,
    )


def _cost_key(resolver: InventoryResolver, dimension: str, line: Any) -> GroupKey:
    """The group a line of dollars falls in: unallocated cost has no principal (and no model
    when the provider reported none), so it gathers under one sentinel row."""
    unallocated = line.unallocated_reason is not None and (
        dimension in PRINCIPAL_DIMENSIONS or (dimension == "model" and line.model is None)
    )
    if unallocated:
        return (line.provider, UNALLOCATED_KEY)
    return _entity_key(resolver, dimension, line)


def _add_usage(
    groups: dict[GroupKey, _Group],
    line: Any,
    dimension: str,
    applied: ClauseFilters,
    resolver: InventoryResolver,
) -> None:
    if dimension == TOKEN_TYPE:
        for name in TOKEN_COLUMNS:
            label = token_type_label(name)
            if not token_type_matches(label, applied):
                continue
            group = groups.setdefault((line.provider, label), _Group())
            group.providers.add(line.provider)
            group.accounts.add(line.provider_account_id)
            group.tokens[name] += int(getattr(line, name))
        return
    group = groups.setdefault(_entity_key(resolver, dimension, line), _Group())
    group.providers.add(line.provider)
    group.accounts.add(line.provider_account_id)
    for name in TOKEN_COLUMNS:
        if token_type_matches(token_type_label(name), applied):
            group.tokens[name] += int(getattr(line, name))
    group.web_search_requests += int(line.web_search_requests)
    group.add_byok(line.byok_amount)
    group.request_count += int(line.request_count)


def _usage_row(
    resolver: InventoryResolver,
    dimension: str,
    key: GroupKey,
    group: _Group,
    allocated: bool,
    cost_total: Decimal,
) -> UsageRow:
    _, external_id = key
    share = None
    if allocated and cost_total > 0:
        share = to_percent(group.amount / cost_total * 100)
    details = group_details(resolver, dimension, key)
    if dimension in ("person", "team"):
        details["providers"] = ",".join(sorted(group.providers))
    return UsageRow(
        key=None if external_id.startswith("__") else external_id,
        label=group_label(resolver, dimension, key),
        tokens=dict(group.tokens),
        web_search_requests=group.web_search_requests,
        amount=group.amount if allocated else None,
        share=share,
        details=details,
        provider=group.provider,
        byok_amount=group.byok_amount,
        request_count=group.request_count,
        person=group_person(resolver, dimension, key),
        provider_account_id=group.provider_account_id,
        provider_account_label=resolver.provider_account_label(group.provider_account_id),
    )


@dataclass
class MoverRow:
    key: str | None
    label: str
    provider: str | None
    amount: Decimal
    previous_amount: Decimal
    delta: Decimal
    # None when the previous month has nothing to divide by, which is what `is_new` reports.
    change_percent: Decimal | None
    is_new: bool
    is_gone: bool
    provider_account_id: int | None = None
    provider_account_label: str | None = None


@dataclass
class MoversReport:
    dimension: str
    allocated: bool
    previous_month: str
    rows: list[MoverRow]


def movers(
    session: Session,
    *,
    org_id: int,
    provider: str,
    window: Window,
    previous: Window,
    previous_month: str,
    dimension: str,
    top: int | None = None,
) -> MoversReport:
    """Rows of `dimension` ranked by the money that moved between `previous` and `window`.

    Both windows need an allocation: without dollars on one side every delta would be the whole
    amount of the other. `allocated=False` reports that instead of a misleading ranking.
    """
    resolver = InventoryResolver(session, org_id, provider)
    current = usage_report(
        session,
        org_id=org_id,
        provider=provider,
        window=window,
        dimension=dimension,
        resolver=resolver,
    )
    before = usage_report(
        session,
        org_id=org_id,
        provider=provider,
        window=previous,
        dimension=dimension,
        resolver=resolver,
    )
    if not (current.allocated and before.allocated):
        return MoversReport(
            dimension=dimension, allocated=False, previous_month=previous_month, rows=[]
        )

    # Sentinel rows (unallocated cost) name no entity to act on; the reconcile page owns them.
    identity = {(row.provider, row.key): row for row in before.rows if row.key is not None}
    rows: list[MoverRow] = []
    for row in current.rows:
        if row.key is None:
            continue
        rows.append(_mover(row, identity.pop((row.provider, row.key), None)))
    rows.extend(_mover(None, row) for row in identity.values())
    rows = [row for row in rows if row.delta != 0]
    rows.sort(key=lambda r: (-abs(r.delta), r.label))
    if top is not None:
        rows = rows[:top]
    return MoversReport(
        dimension=dimension, allocated=True, previous_month=previous_month, rows=rows
    )


def _mover(current: UsageRow | None, before: UsageRow | None) -> MoverRow:
    row = current or before
    assert row is not None
    amount = (current.amount if current else None) or Decimal("0")
    previous_amount = (before.amount if before else None) or Decimal("0")
    change_percent = None
    if previous_amount > 0:
        change_percent = ((amount - previous_amount) / previous_amount * 100).quantize(
            Decimal("0.01")
        )
    return MoverRow(
        key=row.key,
        label=row.label,
        provider=row.provider,
        amount=amount,
        previous_amount=previous_amount,
        delta=amount - previous_amount,
        change_percent=change_percent,
        is_new=previous_amount == 0,
        is_gone=amount == 0,
        provider_account_id=row.provider_account_id,
        provider_account_label=row.provider_account_label,
    )


class _Group:
    def __init__(self) -> None:
        self.tokens: dict[str, int] = dict.fromkeys(TOKEN_COLUMNS, 0)
        self.web_search_requests = 0
        self.request_count = 0
        self.amount = Decimal("0")
        self.providers: set[str] = set()
        self.accounts: set[int] = set()
        self.byok_amount: Decimal | None = None

    @property
    def provider(self) -> str | None:
        return next(iter(self.providers)) if len(self.providers) == 1 else None

    @property
    def provider_account_id(self) -> int | None:
        return next(iter(self.accounts)) if len(self.accounts) == 1 else None

    def add_byok(self, value: Any) -> None:
        if value is None:
            return
        self.byok_amount = (self.byok_amount or Decimal("0")) + Decimal(value)


def _usage_groups(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    filters: ClauseFilters,
    resolver: InventoryResolver,
) -> Any:
    dims = (
        SpendUsageLine.provider,
        SpendUsageLine.api_key_id,
        SpendUsageLine.account_id,
        SpendUsageLine.workspace_id,
        SpendUsageLine.model,
        SpendUsageLine.provider_account_id,
    )
    sums = [
        func.coalesce(func.sum(getattr(SpendUsageLine, name)), 0).label(name)
        for name in TOKEN_COLUMNS
    ]
    web = func.coalesce(func.sum(SpendUsageLine.web_search_requests), 0).label(
        "web_search_requests"
    )
    # No coalesce: a group whose lines all lack a BYOK figure stays None.
    byok = func.sum(SpendUsageLine.byok_amount).label("byok_amount")
    requests = func.coalesce(func.sum(SpendUsageLine.request_count), 0).label("request_count")
    return session.execute(
        select(*dims, *sums, web, byok, requests)
        .where(*line_where(SpendUsageLine, org_id, provider, window, filters, resolver=resolver))
        .group_by(*dims)
    ).all()


def _allocated_groups(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    filters: ClauseFilters,
    resolver: InventoryResolver,
) -> Any:
    dims = (
        SpendAllocatedLine.provider,
        SpendAllocatedLine.api_key_id,
        SpendAllocatedLine.account_id,
        SpendAllocatedLine.workspace_id,
        SpendAllocatedLine.model,
        SpendAllocatedLine.token_type,
        SpendAllocatedLine.unallocated_reason,
        SpendAllocatedLine.provider_account_id,
    )
    return session.execute(
        select(*dims, func.sum(SpendAllocatedLine.amount).label("amount"))
        .where(
            *line_where(SpendAllocatedLine, org_id, provider, window, filters, resolver=resolver)
        )
        .group_by(*dims)
    ).all()


class _DailyLine(NamedTuple):
    """One day of dollars under the columns `spend_allocated_lines` groups by; cost lines
    carry no key, account or unallocated reason."""

    day: date
    provider: str
    api_key_id: str | None
    account_id: str | None
    workspace_id: str | None
    model: str | None
    cost_type: str | None
    token_type: str | None
    unallocated_reason: str | None
    provider_account_id: int | None
    amount: Decimal


SCOPE_TOTAL_KEY: GroupKey = ("__scope__", "__all__")


@dataclass
class Series:
    key: str | None
    label: str
    values: list[Decimal]
    provider: str | None = None

    @property
    def total(self) -> Decimal:
        return sum(self.values, Decimal("0"))


@dataclass
class DailySeries:
    dimension: str
    days: list[date]
    series: list[Series]
    other: list[Decimal] | None
    total: list[Decimal]
    source: str  # "allocated" or "cost"


def daily_series(
    session: Session,
    *,
    org_id: int,
    provider: str,
    window: Window,
    dimension: str,
    top: int = 8,
    filters: Filters | None = None,
) -> DailySeries:
    """Dollars per day for the window, one series per group in `dimension`, zero-filled.

    Reads `spend_allocated_lines` when an allocation covers the window (every dimension,
    unallocated cost shown as its own series); otherwise falls back to `spend_cost_lines`, which
    has no key or account, so `api_key`, `account` and `creator` come back empty.
    """
    if dimension not in SERIES_DIMENSIONS:
        raise InvalidInput(f"unknown dimension {dimension!r}; expected one of {SERIES_DIMENSIONS}")
    applied = validate_filters(filters)
    resolver = InventoryResolver(session, org_id, provider)
    days = list(window.days())
    index = {day: i for i, day in enumerate(days)}

    allocation_scope = (
        exact_filter(applied, "provider", provider) if provider == "all" else provider
    )
    source = "allocated" if allocation_covers(session, org_id, allocation_scope, window) else "cost"
    if source == "allocated":
        rows = _allocated_daily(session, org_id, provider, window, applied, resolver)
    else:
        rows = _cost_daily(session, org_id, provider, window, applied, resolver)

    grouped: dict[GroupKey, list[Decimal]] = {}
    providers: dict[GroupKey, set[str]] = {}
    for line in rows:
        if not _matches(line, applied, resolver, token_type=token_type_label(line.token_type)):
            continue
        key = _series_key(resolver, dimension, line, source)
        if key is None:
            continue
        values = grouped.setdefault(key, [Decimal("0")] * len(days))
        values[index[line.day]] += Decimal(line.amount)
        providers.setdefault(key, set()).add(line.provider)

    ranked = sorted(grouped.items(), key=lambda kv: (-sum(kv[1]), kv[0]))
    return DailySeries(
        dimension=dimension,
        days=days,
        series=_top_series(resolver, dimension, ranked[:top], providers),
        other=_sum_days(ranked[top:], len(days)) if len(ranked) > top else None,
        total=_sum_days(ranked, len(days)),
        source=source,
    )


def _series_key(
    resolver: InventoryResolver, dimension: str, line: Any, source: str
) -> GroupKey | None:
    """None drops the line: cost lines name no principal, so a principal series has nothing
    to show for them."""
    if dimension == "none":
        return SCOPE_TOTAL_KEY
    if dimension == "cost_type":
        return (line.provider, line.cost_type)
    if source == "cost" and dimension in PRINCIPAL_DIMENSIONS:
        return None
    return _cost_key(resolver, dimension, line)


def _top_series(
    resolver: InventoryResolver,
    dimension: str,
    selected: list[tuple[GroupKey, list[Decimal]]],
    providers: dict[GroupKey, set[str]],
) -> list[Series]:
    """Labels that collide across providers carry the provider name."""
    labels = {
        key: "total" if key == SCOPE_TOTAL_KEY else group_label(resolver, dimension, key)
        for key, _ in selected
    }
    label_counts = Counter(labels.values())
    series = []
    for key, values in selected:
        line_provider, external_id = key
        label = labels[key]
        if label_counts[label] > 1 and line_provider in PROVIDERS:
            label = f"{label} - {get_spec(line_provider).label}"
        series.append(
            Series(
                key=None if external_id.startswith("__") else external_id,
                label=label,
                values=values,
                provider=next(iter(providers[key])) if len(providers[key]) == 1 else None,
            )
        )
    return series


def _sum_days(groups: list[tuple[GroupKey, list[Decimal]]], length: int) -> list[Decimal]:
    total = [Decimal("0")] * length
    for _, values in groups:
        for i, value in enumerate(values):
            total[i] += value
    return total


def _allocated_daily(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    filters: ClauseFilters,
    resolver: InventoryResolver,
) -> Any:
    day = utc_day(SpendAllocatedLine.period_start).label("day")
    dims = (
        SpendAllocatedLine.provider,
        SpendAllocatedLine.api_key_id,
        SpendAllocatedLine.account_id,
        SpendAllocatedLine.workspace_id,
        SpendAllocatedLine.model,
        SpendAllocatedLine.cost_type,
        SpendAllocatedLine.token_type,
        SpendAllocatedLine.unallocated_reason,
        SpendAllocatedLine.provider_account_id,
    )
    return session.execute(
        select(day, *dims, func.sum(SpendAllocatedLine.amount).label("amount"))
        .where(
            *line_where(SpendAllocatedLine, org_id, provider, window, filters, resolver=resolver)
        )
        .group_by(day, *dims)
    ).all()


def _cost_daily(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    filters: ClauseFilters,
    resolver: InventoryResolver,
) -> Any:
    day = utc_day(SpendCostLine.period_start).label("day")
    dims = (
        SpendCostLine.provider,
        SpendCostLine.workspace_id,
        SpendCostLine.model,
        SpendCostLine.cost_type,
        SpendCostLine.token_type,
        SpendCostLine.provider_account_id,
    )
    rows = session.execute(
        select(day, *dims, func.sum(SpendCostLine.amount).label("amount"))
        .where(*line_where(SpendCostLine, org_id, provider, window, filters, resolver=resolver))
        .group_by(day, *dims)
    ).all()
    return [
        _DailyLine(
            day=row.day,
            provider=row.provider,
            api_key_id=None,
            account_id=None,
            workspace_id=row.workspace_id,
            model=row.model,
            cost_type=row.cost_type,
            token_type=row.token_type,
            unallocated_reason=None,
            provider_account_id=row.provider_account_id,
            amount=row.amount,
        )
        for row in rows
    ]
