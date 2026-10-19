"""The filter contract every spend read shares: bounded clauses of an operator and
values per dimension, how a line matches them in Python, and the SQL WHERE over the line tables.

`Filters` maps a dimension to a plain value or a `FilterClause`; `normalize_filters` turns the
plain values into clauses and enforces the bounds."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import and_, false, func, not_, or_, true

from costura.errors import InvalidInput
from costura.providers.registry import PROVIDERS, provider_origin
from costura.spend import FILTER_KEYS
from costura.spend.dimensions import (
    KEY_API_KEY_REQUEST,
    KEY_DEFAULT_WORKSPACE,
    KEY_NO_MODEL,
    KEY_OAUTH,
    KEY_PLAYGROUND,
    KEY_UNKNOWN_CREATOR,
    line_person,
)
from costura.spend.inventory import (
    InventoryResolver,
)
from costura.spend.scope import provider_clause
from costura.spend.taxonomy import (
    MODEL_DIMENSIONS,
    TOKEN_TYPE,
    resolve,
)
from costura.spend.window import Window

FilterOperator = Literal[
    "is",
    "is_not",
    "one_of",
    "not_one_of",
    "contains",
    "not_contains",
    "exists",
    "not_exists",
]


FILTER_OPERATORS: tuple[str, ...] = (
    "is",
    "is_not",
    "one_of",
    "not_one_of",
    "contains",
    "not_contains",
    "exists",
    "not_exists",
)


MAX_FILTERS = 20

MAX_FILTER_VALUES = 20

MAX_FILTER_TEXT = 200


@dataclass(frozen=True)
class FilterClause:
    op: FilterOperator
    values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(self.values))
        if self.op not in FILTER_OPERATORS:
            raise InvalidInput(f"filter op must be one of {FILTER_OPERATORS}")
        if self.op in ("exists", "not_exists"):
            if self.values:
                raise InvalidInput(f"{self.op} does not accept values")
            return
        if not 1 <= len(self.values) <= MAX_FILTER_VALUES:
            raise InvalidInput(
                f"{self.op} values must contain between 1 and {MAX_FILTER_VALUES} strings"
            )
        if self.op in ("is", "is_not", "contains", "not_contains") and len(self.values) != 1:
            raise InvalidInput(f"{self.op} accepts exactly one value")
        if any(
            not isinstance(value, str) or not value or len(value) > MAX_FILTER_TEXT
            for value in self.values
        ):
            raise InvalidInput(
                f"filter values must be non-empty strings up to {MAX_FILTER_TEXT} characters"
            )


FilterValue = str | FilterClause

Filters = Mapping[str, FilterValue]

ClauseFilters = Mapping[str, FilterClause]


def filter_clause(value: FilterValue | Mapping[str, Any]) -> FilterClause:
    if isinstance(value, FilterClause):
        return value
    if isinstance(value, str):
        return FilterClause("is", (value,))
    if not isinstance(value, Mapping) or set(value) != {"op", "values"}:
        raise InvalidInput("filter clauses must contain only op and values")
    op = value["op"]
    values = value["values"]
    if not isinstance(op, str) or not isinstance(values, (list, tuple)):
        raise InvalidInput("filter clauses require a string op and a list of values")
    return FilterClause(op, tuple(values))  # type: ignore[arg-type]


def normalize_filters(
    filters: Mapping[str, FilterValue | Mapping[str, Any]] | None,
    *,
    allowed: tuple[str, ...] | None = None,
) -> ClauseFilters:
    if len(filters or {}) > MAX_FILTERS:
        raise InvalidInput(f"filters accepts at most {MAX_FILTERS} values")
    result: ClauseFilters = {}
    for key, value in (filters or {}).items():
        if not isinstance(key, str) or not key or len(key) > 80:
            raise InvalidInput("filter names must be non-empty strings up to 80 characters")
        clause = filter_clause(value)
        result[key] = clause
    if allowed is not None:
        unknown = set(result) - set(allowed)
        if unknown:
            raise InvalidInput(f"unknown filters {sorted(unknown)}; expected {allowed}")
    return result


def filter_matches(candidates: tuple[str | None, ...], clause: FilterClause) -> bool:
    available = tuple(value for value in candidates if value not in (None, ""))
    present = tuple(value for value in available if value not in ABSENT_FILTER_VALUES)
    if clause.op == "exists":
        return bool(present)
    if clause.op == "not_exists":
        return not present
    folded = tuple(value.casefold() for value in available)
    expected = tuple(value.casefold() for value in clause.values)
    if clause.op in ("is", "one_of"):
        return any(candidate == value for candidate in folded for value in expected)
    if clause.op in ("is_not", "not_one_of"):
        return all(candidate != value for candidate in folded for value in expected)
    if clause.op == "contains":
        return any(value in candidate for candidate in folded for value in expected)
    return all(value not in candidate for candidate in folded for value in expected)


def validate_filters(filters: Filters | None) -> ClauseFilters:
    return normalize_filters(filters, allowed=FILTER_KEYS)


def person_clause(
    table: Any,
    identities: list[tuple[str, str]],
    resolver: InventoryResolver,
    marked_keys: list[tuple[str, str]] | None = None,
) -> Any:
    """Rows of one person: direct account usage (no API key on the line), their personal
    Claude Code keys, and the keys a member marked as theirs. The same rule as `line_person`:
    a line with an API key follows the key, never the user the provider reports beside it."""
    has_api_key = hasattr(table, "api_key_id")
    marked_keys = marked_keys if has_api_key else []
    if not hasattr(table, "account_id") or not (identities or marked_keys):
        return false()
    clauses = [
        (table.provider == line_provider) & (table.api_key_id == key_id)
        for line_provider, key_id in marked_keys or []
    ]
    for line_provider, account_id in identities:
        principal = table.account_id == account_id
        if has_api_key:
            principal = table.api_key_id.is_(None) & principal
            keys = [
                key_id
                for provider, key_id in resolver.personal_key_identities_of(account_id)
                if provider == line_provider
            ]
            if keys:
                principal = or_(principal, table.api_key_id.in_(keys))
        clauses.append((table.provider == line_provider) & principal)
    return or_(*clauses)


def creator_clause(table: Any, resolver: InventoryResolver, creator_id: str) -> Any:
    """Rows grouped under one creator identity: their API keys plus direct account usage."""
    if not hasattr(table, "api_key_id") or not hasattr(table, "account_id"):
        return false()
    creator = None if creator_id == KEY_UNKNOWN_CREATOR else creator_id
    keys = resolver.api_key_identities_created_by(creator)
    clauses = [
        (table.provider == line_provider) & (table.api_key_id == api_key_id)
        for line_provider, api_key_id in keys
    ]
    if creator is None:
        clauses.append(table.api_key_id.is_(None) & table.account_id.is_(None))
    else:
        clauses.append(table.api_key_id.is_(None) & (table.account_id == creator))
    return or_(*clauses)


def _sentinel_clauses(table: Any, column: Any, clause: FilterClause) -> list[Any]:
    """Rows the sentinel keys select: a NULL natural id, with the account present or absent."""
    sentinels = set(clause.values) & {
        KEY_OAUTH,
        KEY_PLAYGROUND,
        KEY_API_KEY_REQUEST,
        KEY_DEFAULT_WORKSPACE,
        KEY_NO_MODEL,
    }
    if sentinels and clause.op != "is":
        raise InvalidInput("sentinel filter values support only the is operator")
    value = clause.values[0] if clause.values else None
    if value == KEY_OAUTH:
        return [column.is_(None), table.account_id.is_not(None)]
    if value == KEY_PLAYGROUND:
        return [column.is_(None), table.account_id.is_(None)]
    if value in (KEY_API_KEY_REQUEST, KEY_DEFAULT_WORKSPACE, KEY_NO_MODEL):
        return [column.is_(None)]
    return [_column_clause(column, clause)]


def _provider_account_clause(table: Any, clause: FilterClause) -> Any:
    column = getattr(table, "provider_account_id", None)
    if column is None:
        return true() if clause.op == "not_exists" else false()
    if clause.op in ("contains", "not_contains"):
        raise InvalidInput("provider_account does not support contains operators")
    if clause.op in ("exists", "not_exists"):
        return _column_clause(column, clause)
    if any(not value.isdigit() for value in clause.values):
        raise InvalidInput("provider_account filter values must be numeric")
    numeric = tuple(int(value) for value in clause.values)
    if clause.op == "is":
        return column == numeric[0]
    if clause.op == "is_not":
        return or_(column != numeric[0], column.is_(None))
    if clause.op == "one_of":
        return column.in_(numeric)
    return or_(column.not_in(numeric), column.is_(None))


def line_where(
    table: Any,
    org_id: int,
    provider: str,
    window: Window,
    filters: Filters,
    *,
    resolver: InventoryResolver | None = None,
) -> list[Any]:
    """WHERE clauses for a line table: org, provider, window, then one per filter.

    Sentinel keys (`__default_workspace__`, `__oauth__`, ...) select the rows whose natural id
    is NULL, so a drill-down from any usage row round-trips. A filter on a column the table
    lacks (`api_key` on cost lines) matches nothing. `person` needs the `resolver` to expand
    the e-mail into identities.
    """
    clauses = [
        table.organization_id == org_id,
        provider_clause(table.provider, provider),
        table.period_start >= window.start,
        table.period_start < window.end,
    ]
    normalized = normalize_filters(filters)
    for name, clause in normalized.items():
        if name == "origin":
            providers = [
                slug for slug, spec in PROVIDERS.items() if filter_matches((spec.surface,), clause)
            ]
            clauses.append(table.provider.in_(providers) if providers else false())
            continue
        if name == "person":
            if resolver is None:
                raise InvalidInput("the person filter needs an inventory resolver")
            _require_expandable_operator(name, clause)
            identities = [
                identity
                for value in clause.values
                for identity in resolver.person_identities(value)
            ]
            marked = [
                identity for value in clause.values for identity in resolver.marked_keys_of(value)
            ]
            clauses.append(
                _expanded_clause(person_clause(table, identities, resolver, marked), clause)
            )
            continue
        if name == "creator":
            if resolver is None:
                raise InvalidInput("the creator filter needs an inventory resolver")
            _require_expandable_operator(name, clause)
            matches = [creator_clause(table, resolver, value) for value in clause.values]
            clauses.append(_expanded_clause(or_(*matches) if matches else false(), clause))
            continue
        if name == "provider_account":
            clauses.append(_provider_account_clause(table, clause))
            continue
        column_name = {"api_key": "api_key_id", "account": "account_id"}.get(name, name)
        column_name = "workspace_id" if name == "workspace" else column_name
        column = getattr(table, column_name, None)
        if column is None:
            clauses.append(true() if clause.op == "not_exists" else false())
            continue
        clauses.extend(_sentinel_clauses(table, column, clause))
    return clauses


def _require_expandable_operator(name: str, clause: FilterClause) -> None:
    if clause.op not in ("is", "is_not", "one_of", "not_one_of"):
        raise InvalidInput(f"{name} supports only is, is_not, one_of and not_one_of SQL filters")


def _expanded_clause(match: Any, clause: FilterClause) -> Any:
    if clause.op in ("is", "one_of"):
        return match
    return not_(func.coalesce(match, false()))


def _column_clause(column: Any, clause: FilterClause) -> Any:
    if clause.op == "is":
        return column == clause.values[0]
    if clause.op == "is_not":
        return or_(column != clause.values[0], column.is_(None))
    if clause.op == "one_of":
        return column.in_(clause.values)
    if clause.op == "not_one_of":
        return or_(column.not_in(clause.values), column.is_(None))
    if clause.op == "contains":
        return column.ilike(_contains_pattern(clause.values[0]), escape="\\")
    if clause.op == "not_contains":
        return or_(
            column.is_(None),
            and_(
                *(
                    column.not_ilike(_contains_pattern(value), escape="\\")
                    for value in clause.values
                )
            ),
        )
    if clause.op == "exists":
        return column.is_not(None)
    return column.is_(None)


def _contains_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


ABSENT_FILTER_VALUES = frozenset({KEY_UNKNOWN_CREATOR})


def exact_filter(filters: ClauseFilters, name: str, default: str) -> str:
    value = filters.get(name)
    if value is None:
        return default
    clause = filter_clause(value)
    return clause.values[0] if clause.op == "is" else default


def token_type_matches(label: str, filters: ClauseFilters) -> bool:
    clause = filters.get(TOKEN_TYPE)
    return clause is None or filter_matches((label,), clause)


def derived_matches(
    provider: str,
    api_key_id: str | None,
    account_id: str | None,
    workspace_id: str | None,
    model: str | None,
    provider_account_id: int | str | None,
    filters: Filters,
    resolver: InventoryResolver,
    *,
    token_type: str | None = None,
    include_token_type: bool = True,
) -> bool:
    canonical = resolve(provider, model)
    if api_key_id is None:
        creator = account_id or KEY_UNKNOWN_CREATOR
    else:
        creator = resolver.creator_of(provider, api_key_id) or KEY_UNKNOWN_CREATOR
    provider_account = None if provider_account_id is None else str(provider_account_id)
    context: dict[str, tuple[str | None, ...]] = {
        "origin": (provider_origin(provider),),
        "person": (line_person(resolver, provider, api_key_id, account_id),),
        "creator": (creator,),
        "provider_account": (
            provider_account,
            (
                resolver.provider_account_label(int(provider_account))
                if provider_account is not None and provider_account.isdigit()
                else provider_account
            ),
        ),
        **{name: (canonical.value(name),) for name in MODEL_DIMENSIONS},
    }
    if include_token_type:
        context[TOKEN_TYPE] = (token_type,)
    return all(
        name not in context or filter_matches(context[name], filter_clause(clause))
        for name, clause in filters.items()
    )
