"""Which provider (and account) an id in an organization belongs to: an API key, workspace,
user account, model or anomaly. The web resolves entity links through this."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import (
    ProviderApiKey,
    ProviderModelSeen,
    ProviderUser,
    ProviderWorkspace,
    SpendAnomaly,
    SpendCostLine,
)

ENTITY_KINDS = ("key", "workspace", "account", "model", "anomaly")
INVENTORY_TABLES = {"key": ProviderApiKey, "workspace": ProviderWorkspace, "account": ProviderUser}


@dataclass(frozen=True)
class EntityOwner:
    provider: str
    provider_account_id: int | None


def resolve_entity(
    session: Session,
    org_id: int,
    kind: str,
    entity_id: str,
    *,
    scope: str | None = None,
    account: int | None = None,
) -> EntityOwner | None:
    """None when nothing in the organization matches. A model name several providers share
    resolves to `scope` when it is one of them, else to the provider that saw it last. An
    `account` picks one console when the same external id exists on two of a provider's."""
    if kind == "anomaly":
        return _anomaly_owner(session, org_id, entity_id)
    if kind == "model":
        candidates = _model_providers(session, org_id, entity_id)
        if not candidates:
            return None
        return EntityOwner(scope if scope in candidates else candidates[0], None)
    table = INVENTORY_TABLES[kind]
    stmt = (
        select(table)
        .where(table.organization_id == org_id, table.external_id == entity_id)
        .order_by(table.provider, table.id)
    )
    if account is not None:
        stmt = stmt.where(table.provider_account_id == account)
    rows = list(session.scalars(stmt))
    chosen = next((r for r in rows if r.provider == scope), rows[0] if rows else None)
    if chosen is None:
        return None
    return EntityOwner(chosen.provider, getattr(chosen, "provider_account_id", None))


def _anomaly_owner(session: Session, org_id: int, entity_id: str) -> EntityOwner | None:
    if not entity_id.isdigit():
        return None
    row = session.get(SpendAnomaly, int(entity_id))
    if row is None or row.organization_id != org_id:
        return None
    return EntityOwner(row.provider, getattr(row, "provider_account_id", None))


def _model_providers(session: Session, org_id: int, model: str) -> list[str]:
    """Providers that billed the model, most recently seen first: from `provider_models_seen`,
    and from the cost lines only when the model was never recorded there."""
    seen = list(
        session.scalars(
            select(ProviderModelSeen.provider)
            .where(ProviderModelSeen.organization_id == org_id, ProviderModelSeen.model == model)
            .order_by(ProviderModelSeen.last_seen.desc(), ProviderModelSeen.provider)
        )
    )
    if seen:
        return seen
    newest = func.max(SpendCostLine.period_start)
    return [
        name
        for name, _ in session.execute(
            select(SpendCostLine.provider, newest)
            .where(SpendCostLine.organization_id == org_id, SpendCostLine.model == model)
            .group_by(SpendCostLine.provider)
            .order_by(newest.desc())
        )
    ]
