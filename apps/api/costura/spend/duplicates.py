"""Two accounts of one provider that report the same organization: their inventories share
most of their ids, so their spend is counted twice."""

from dataclasses import dataclass
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import ProviderAccount, ProviderApiKey, ProviderUser, ProviderWorkspace
from costura.spend.scope import provider_clause

MIN_SHARED = 3
SHARED_RATIO = 0.5


@dataclass(frozen=True)
class DuplicatePair:
    provider: str
    first: ProviderAccount
    second: ProviderAccount
    shared: int


def duplicate_accounts(session: Session, org_id: int, provider: str) -> list[DuplicatePair]:
    """Pairs of connected accounts of one provider whose key, user and workspace ids overlap
    by at least `MIN_SHARED` ids and half of the smaller inventory."""
    accounts = list(
        session.scalars(
            select(ProviderAccount)
            .where(
                ProviderAccount.organization_id == org_id,
                provider_clause(ProviderAccount.provider, provider),
                ProviderAccount.disconnected_at.is_(None),
            )
            .order_by(ProviderAccount.id)
        )
    )
    ids: dict[int, set[str]] = {account.id: set() for account in accounts}
    for model, kind in ((ProviderApiKey, "key"), (ProviderUser, "user"), (ProviderWorkspace, "ws")):
        rows = session.execute(
            select(model.provider_account_id, model.external_id).where(
                model.organization_id == org_id,
                model.provider_account_id.in_(list(ids)),
            )
        )
        for account_id, external_id in rows:
            ids[account_id].add(f"{kind}:{external_id}")
    pairs: list[DuplicatePair] = []
    for first, second in combinations(accounts, 2):
        if first.provider != second.provider:
            continue
        shared = len(ids[first.id] & ids[second.id])
        smaller = min(len(ids[first.id]), len(ids[second.id]))
        if shared >= MIN_SHARED and smaller and shared / smaller >= SHARED_RATIO:
            pairs.append(DuplicatePair(first.provider, first, second, shared))
    return pairs
