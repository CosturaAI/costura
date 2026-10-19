"""Readers behind `query_spend`: pick the source table for a spec and window, read grouped facts
from it, apply the filters SQL cannot express, and fold each fact under its identity.

Billed money reads allocated lines when allocation covers the whole window and cost lines
otherwise; BYOK money, tokens and web-search requests read usage lines."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.errors import InvalidInput
from costura.models import SpendAllocatedLine, SpendCostLine, SpendUsageLine
from costura.providers.registry import ALL, PROVIDERS, provider_origin
from costura.spend.allocation_check import allocation_covers
from costura.spend.dimensions import (
    KEY_UNKNOWN_CREATOR,
    PRINCIPAL_DIMENSIONS,
    PYTHON_FILTER_DIMENSIONS,
    UNALLOCATED_KEY,
    GroupKey,
    group_key,
    line_person,
)
from costura.spend.filters import (
    FilterClause,
    Filters,
    filter_matches,
    line_where,
)
from costura.spend.inventory import InventoryResolver
from costura.spend.query_contract import (
    MEASURES,
    Identity,
    QuerySpec,
)
from costura.spend.sql import utc_day
from costura.spend.taxonomy import MODEL_DIMENSIONS, TOKEN_TYPE, resolve, token_type_label
from costura.spend.usage import TOKEN_COLUMNS
from costura.spend.window import Window

OTHER_TOKEN_TYPE = "Other"


@dataclass(frozen=True, slots=True)
class QueryFact:
    """One grouped line read from a spend table, before Python-side filters and grouping.
    A column the source table does not have stays None."""

    day: date
    provider: str
    provider_account_id: int | None
    value: Decimal | int | None
    api_key_id: str | None = None
    account_id: str | None = None
    workspace_id: str | None = None
    model: str | None = None
    cost_type: str | None = None
    unallocated: str | None = None
    token_type: str = OTHER_TOKEN_TYPE


@dataclass
class FactRead:
    values: dict[Identity, dict[date, Decimal]]
    providers: dict[Identity, set[str]]


def fact_source(session: Session, org_id: int, spec: QuerySpec, window: Window) -> str:
    if spec.measure != "billed_usd":
        return "usage"
    scope = _exact_filter(spec.filters, "provider", ALL)
    return "allocated" if allocation_covers(session, org_id, scope, window) else "cost"


def read_facts(
    session: Session,
    org_id: int,
    spec: QuerySpec,
    window: Window,
    source: str,
    resolver: InventoryResolver,
) -> FactRead:
    if spec.measure == "billed_usd":
        facts = _billed_facts(session, org_id, spec, window, source, resolver)
    else:
        facts = _usage_facts(session, org_id, spec, window, resolver)
    values: dict[Identity, dict[date, Decimal]] = {}
    providers: dict[Identity, set[str]] = {}
    for fact in facts:
        if not _python_filters_match(fact, spec.filters, resolver):
            continue
        identity = _identity(resolver, spec.dimensions, fact, source)
        if identity is None:
            continue
        daily = values.setdefault(identity, {})
        daily[fact.day] = daily.get(fact.day, Decimal("0")) + Decimal(fact.value or 0)
        providers.setdefault(identity, set()).add(fact.provider)
    return FactRead(values=values, providers=providers)


def _billed_facts(
    session: Session,
    org_id: int,
    spec: QuerySpec,
    window: Window,
    source: str,
    resolver: InventoryResolver,
) -> list[QueryFact]:
    if source == "allocated":
        table = SpendAllocatedLine
        day = utc_day(table.period_start)
        dims = (
            table.provider,
            table.api_key_id,
            table.account_id,
            table.workspace_id,
            table.model,
            table.token_type,
            table.cost_type,
            table.unallocated_reason,
            table.provider_account_id,
        )
        rows = session.execute(
            select(day, *dims, func.sum(table.amount))
            .where(*_where(table, org_id, window, spec.filters, resolver))
            .group_by(day, *dims)
        ).all()
        return [
            QueryFact(
                day=day,
                provider=provider,
                provider_account_id=provider_account,
                value=amount,
                api_key_id=api_key,
                account_id=account,
                workspace_id=workspace,
                model=model,
                cost_type=cost_type,
                unallocated=reason,
                token_type=token_type_label(token_type),
            )
            for (
                day,
                provider,
                api_key,
                account,
                workspace,
                model,
                token_type,
                cost_type,
                reason,
                provider_account,
                amount,
            ) in rows
        ]

    table = SpendCostLine
    day = utc_day(table.period_start)
    dims = (
        table.provider,
        table.workspace_id,
        table.model,
        table.token_type,
        table.cost_type,
        table.provider_account_id,
    )
    rows = session.execute(
        select(day, *dims, func.sum(table.amount))
        .where(*_where(table, org_id, window, spec.filters, resolver))
        .group_by(day, *dims)
    ).all()
    return [
        QueryFact(
            day=day,
            provider=provider,
            provider_account_id=account,
            value=amount,
            workspace_id=workspace,
            model=model,
            cost_type=cost_type,
            token_type=token_type_label(token_type),
        )
        for day, provider, workspace, model, token_type, cost_type, account, amount in rows
    ]


def _usage_facts(
    session: Session,
    org_id: int,
    spec: QuerySpec,
    window: Window,
    resolver: InventoryResolver,
) -> list[QueryFact]:
    table = SpendUsageLine
    day = utc_day(table.period_start)
    dims = (
        table.provider,
        table.api_key_id,
        table.account_id,
        table.workspace_id,
        table.model,
        table.provider_account_id,
    )
    where = _where(table, org_id, window, spec.filters, resolver)
    if TOKEN_TYPE in (*spec.dimensions, *spec.filters):
        token_columns = _token_columns_for_measure(spec.measure)
        rows = session.execute(
            select(day, *dims, *(func.sum(getattr(table, name)) for name in token_columns))
            .where(*where)
            .group_by(day, *dims)
        ).all()
        return [
            QueryFact(
                day=day,
                provider=provider,
                provider_account_id=account_id,
                value=amount,
                api_key_id=api_key,
                account_id=account,
                workspace_id=workspace,
                model=model,
                token_type=token_type_label(name),
            )
            for (day, provider, api_key, account, workspace, model, account_id, *amounts) in rows
            for name, amount in zip(token_columns, amounts, strict=True)
        ]
    rows = session.execute(
        select(day, *dims, _measure_expression(spec.measure)).where(*where).group_by(day, *dims)
    ).all()
    return [
        QueryFact(
            day=day,
            provider=provider,
            provider_account_id=account_id,
            value=amount,
            api_key_id=api_key,
            account_id=account,
            workspace_id=workspace,
            model=model,
        )
        for day, provider, api_key, account, workspace, model, account_id, amount in rows
    ]


def _where(
    table: Any, org_id: int, window: Window, filters: Filters, resolver: InventoryResolver
) -> list[Any]:
    # `origin` is not in PYTHON_FILTER_DIMENSIONS: line_where turns it into provider IN (...).
    sql_filters = {
        key: value for key, value in filters.items() if key not in PYTHON_FILTER_DIMENSIONS
    }
    return line_where(table, org_id, ALL, window, sql_filters, resolver=resolver)


def _token_columns_for_measure(measure: str) -> tuple[str, ...]:
    columns = {
        "tokens_input": ("uncached_input_tokens",),
        "tokens_output": ("output_tokens",),
        "tokens_cache_read": ("cache_read_tokens",),
        "tokens_cache_write": ("cache_creation_5m_tokens", "cache_creation_1h_tokens"),
        "tokens_total": TOKEN_COLUMNS,
    }
    return columns[measure]


def _measure_expression(measure: str) -> Any:
    if measure == "byok_usd":
        return func.coalesce(func.sum(SpendUsageLine.byok_amount), 0)
    if measure == "tokens_input":
        return func.coalesce(func.sum(SpendUsageLine.uncached_input_tokens), 0)
    if measure == "tokens_output":
        return func.coalesce(func.sum(SpendUsageLine.output_tokens), 0)
    if measure == "tokens_cache_read":
        return func.coalesce(func.sum(SpendUsageLine.cache_read_tokens), 0)
    if measure == "tokens_cache_write":
        return func.coalesce(
            func.sum(
                SpendUsageLine.cache_creation_5m_tokens + SpendUsageLine.cache_creation_1h_tokens
            ),
            0,
        )
    if measure == "requests_web_search":
        return func.coalesce(func.sum(SpendUsageLine.web_search_requests), 0)
    if measure == "requests":
        return func.coalesce(func.sum(SpendUsageLine.request_count), 0)
    if measure == "tokens_total":
        return func.coalesce(
            func.sum(sum(getattr(SpendUsageLine, name) for name in TOKEN_COLUMNS)),
            0,
        )
    raise InvalidInput(f"measure must be one of {MEASURES}")


def _identity(
    resolver: InventoryResolver,
    dimensions: tuple[str, ...],
    fact: QueryFact,
    source: str,
) -> Identity | None:
    if source == "cost" and any(d in PRINCIPAL_DIMENSIONS for d in dimensions):
        return None
    result: list[GroupKey] = []
    for dimension in dimensions:
        if dimension == "cost_type":
            result.append((fact.provider, fact.cost_type or "(none)"))
        elif dimension in MODEL_DIMENSIONS:
            canonical = resolve(fact.provider, fact.model, day=fact.day)
            result.append(("canonical", canonical.value(dimension)))
        elif dimension == TOKEN_TYPE:
            result.append(("canonical", fact.token_type))
        elif fact.unallocated is not None and (
            dimension in PRINCIPAL_DIMENSIONS or (dimension == "model" and fact.model is None)
        ):
            result.append((fact.provider, UNALLOCATED_KEY))
        else:
            result.append(
                group_key(
                    resolver,
                    dimension,
                    fact.provider,
                    fact.api_key_id,
                    fact.account_id,
                    fact.workspace_id,
                    fact.model,
                    fact.provider_account_id,
                )
            )
    return tuple(result)


def _exact_filter(filters: Filters, name: str, default: str) -> str:
    value = filters.get(name)
    if not isinstance(value, FilterClause) or value.op != "is":
        return default
    return value.values[0]


def _python_filters_match(fact: QueryFact, filters: Filters, resolver: InventoryResolver) -> bool:
    if not any(key in PYTHON_FILTER_DIMENSIONS for key in filters):
        return True
    provider = fact.provider
    canonical = resolve(provider, fact.model, day=fact.day)
    if fact.api_key_id is None:
        creator = fact.account_id or KEY_UNKNOWN_CREATOR
    else:
        creator = resolver.creator_of(provider, fact.api_key_id) or KEY_UNKNOWN_CREATOR
    provider_account = None if fact.provider_account_id is None else str(fact.provider_account_id)
    context: dict[str, tuple[str | None, ...]] = {
        "origin": (provider_origin(provider) if provider in PROVIDERS else provider,),
        "person": (line_person(resolver, provider, fact.api_key_id, fact.account_id),),
        "creator": (creator,),
        "provider_account": (
            provider_account,
            resolver.provider_account_label(fact.provider_account_id),
        ),
        **{key: (canonical.value(key),) for key in MODEL_DIMENSIONS},
        TOKEN_TYPE: (fact.token_type,),
    }
    return all(
        key not in context or filter_matches(context[key], clause)
        for key, clause in filters.items()
        if isinstance(clause, FilterClause)
    )
