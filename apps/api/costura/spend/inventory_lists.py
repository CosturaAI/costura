"""Reads behind the inventory pages: one row by provider id, the paged lists of keys,
workspaces and users, the active-key count per workspace and the sync run history."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from costura.errors import NotFound
from costura.models import ProviderApiKey, ProviderSyncRun, ProviderUser, ProviderWorkspace
from costura.spend.scope import provider_clause

LIST_LIMIT_DEFAULT = 500
LIST_LIMIT_MAX = 2000


@dataclass(frozen=True)
class Page[Row]:
    rows: list[Row]
    total: int
    limit: int
    offset: int


def inventory_row[Row: (ProviderApiKey, ProviderWorkspace, ProviderUser)](
    session: Session,
    model: type[Row],
    org_id: int,
    provider: str,
    external_id: str,
    account: int | None,
    missing: str,
) -> Row:
    """One row by provider id, missing or not. `account` picks one console when the same
    external id exists on two. 404 (`NotFound`) with `missing` when the inventory never saw
    it."""
    statement = select(model).where(
        model.organization_id == org_id,
        provider_clause(model.provider, provider),
        model.external_id == external_id,
    )
    if account is not None:
        statement = statement.where(model.provider_account_id == account)
    row = session.scalars(statement.order_by(model.id)).first()
    if row is None:
        raise NotFound(missing)
    return row


def _page[Row](session: Session, statement: Select[Any], *, limit: int, offset: int) -> Page[Row]:
    total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    rows = list(session.scalars(statement.limit(limit).offset(offset)))
    return Page(rows=rows, total=int(total or 0), limit=limit, offset=offset)


def _listing[Row: (ProviderApiKey, ProviderWorkspace, ProviderUser)](
    model: type[Row], org_id: int, provider: str, include_missing: bool
) -> Select[Any]:
    statement = select(model).where(
        model.organization_id == org_id, provider_clause(model.provider, provider)
    )
    if not include_missing:
        statement = statement.where(model.missing_since.is_(None))
    return statement


def api_keys(
    session: Session,
    org_id: int,
    provider: str,
    *,
    include_missing: bool,
    limit: int = LIST_LIMIT_DEFAULT,
    offset: int = 0,
) -> Page[ProviderApiKey]:
    statement = _listing(ProviderApiKey, org_id, provider, include_missing).order_by(
        ProviderApiKey.name, ProviderApiKey.external_id
    )
    return _page(session, statement, limit=limit, offset=offset)


def workspaces(
    session: Session,
    org_id: int,
    provider: str,
    *,
    include_missing: bool,
    limit: int = LIST_LIMIT_DEFAULT,
    offset: int = 0,
) -> Page[ProviderWorkspace]:
    statement = _listing(ProviderWorkspace, org_id, provider, include_missing).order_by(
        ProviderWorkspace.name, ProviderWorkspace.external_id
    )
    return _page(session, statement, limit=limit, offset=offset)


def users(
    session: Session,
    org_id: int,
    provider: str,
    *,
    include_missing: bool,
    limit: int = LIST_LIMIT_DEFAULT,
    offset: int = 0,
) -> Page[ProviderUser]:
    statement = _listing(ProviderUser, org_id, provider, include_missing).order_by(
        ProviderUser.email, ProviderUser.id
    )
    return _page(session, statement, limit=limit, offset=offset)


def active_key_counts(
    session: Session, org_id: int, provider: str
) -> dict[tuple[str, str | None], int]:
    """Keys still present in the inventory, per (provider, workspace)."""
    return {
        (line_provider, workspace_id): int(count)
        for line_provider, workspace_id, count in session.execute(
            select(ProviderApiKey.provider, ProviderApiKey.workspace_external_id, func.count())
            .where(
                ProviderApiKey.organization_id == org_id,
                provider_clause(ProviderApiKey.provider, provider),
                ProviderApiKey.missing_since.is_(None),
            )
            .group_by(ProviderApiKey.provider, ProviderApiKey.workspace_external_id)
        ).all()
    }


def sync_runs(
    session: Session, org_id: int, provider: str, *, limit: int, endpoint: str | None
) -> list[ProviderSyncRun]:
    """Newest provider sync runs of the scope, optionally of one endpoint."""
    statement = select(ProviderSyncRun).where(
        ProviderSyncRun.organization_id == org_id,
        provider_clause(ProviderSyncRun.provider, provider),
    )
    if endpoint:
        statement = statement.where(ProviderSyncRun.endpoint == endpoint)
    return list(session.scalars(statement.order_by(ProviderSyncRun.id.desc()).limit(limit)))
