"""Provider scope of a read: one registered provider, or `all` for the union of every provider.

Writes and provider-specific checks (sync, reconcile control totals, connections, budgets) take
a concrete provider; the read paths that aggregate (usage, series, summary, anomalies, budget
statuses, inventory lists) accept `all` and filter with `provider IN (...)`.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import true

from costura.providers.registry import ALL, provider_names


def is_all(scope: str) -> bool:
    return scope == ALL


def scope_providers(scope: str) -> Sequence[str]:
    return provider_names() if scope == ALL else (scope,)


def provider_clause(column: Any, scope: str) -> Any:
    """`column = scope`, or `column IN (every registered provider)` for `all`."""
    if scope == ALL:
        return column.in_(provider_names())
    return column == scope


def account_clause(column: Any, account_id: int | None) -> Any:
    """`column = account_id`, or no restriction when no account is named: a read over every
    account of the provider."""
    if account_id is None:
        return true()
    return column == account_id


__all__ = ["ALL", "account_clause", "is_all", "provider_clause", "scope_providers"]
