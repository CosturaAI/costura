from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import ProviderApiKey, SpendUsageLine
from costura.spend.inventory import InventoryResolver
from costura.spend.owners import (
    ASSIGNED,
    KEY_CREATOR,
    WORKSPACE_ADMIN,
    Assignments,
    key_owners,
    load_assignments,
)

OwnerSource = Literal["assigned", "creator", "workspace_admin"]
LastUseSource = Literal["reported", "derived"]

OWNER_SOURCES: dict[str, OwnerSource] = {
    ASSIGNED: "assigned",
    KEY_CREATOR: "creator",
    WORKSPACE_ADMIN: "workspace_admin",
}


@dataclass(frozen=True)
class KeyPosture:
    owner: str | None
    owner_source: OwnerSource | None
    creator_left: bool
    last_used_at: datetime | None
    last_used_source: LastUseSource | None


class PostureReader:
    def __init__(
        self,
        session: Session,
        org_id: int,
        resolver: InventoryResolver,
        keys: Sequence[ProviderApiKey],
    ) -> None:
        self._resolver = resolver
        self._assignments: dict[str, Assignments] = {
            provider: load_assignments(session, org_id, provider)
            for provider in {key.provider for key in keys}
        }
        self._derived = derived_last_use(session, org_id, keys)

    def of(self, key: ProviderApiKey) -> KeyPosture:
        owners = key_owners(
            self._resolver, key.provider, key.external_id, self._assignments.get(key.provider)
        )
        owner = owners[0] if owners else None
        last_used_at, source = key.last_used_at, "reported" if key.last_used_at else None
        if last_used_at is None:
            last_used_at = self._derived.get((key.provider, key.external_id))
            source = "derived" if last_used_at is not None else None
        return KeyPosture(
            owner=owner.email if owner else None,
            owner_source=OWNER_SOURCES.get(owner.role) if owner else None,
            creator_left=self._resolver.user_left(key.provider, key.created_by_external_id),
            last_used_at=last_used_at,
            last_used_source=source,
        )


def derived_last_use(
    session: Session, org_id: int, keys: Sequence[ProviderApiKey]
) -> dict[tuple[str, str], datetime]:
    ids = {key.external_id for key in keys}
    if not ids:
        return {}
    rows = session.execute(
        select(
            SpendUsageLine.provider,
            SpendUsageLine.api_key_id,
            func.max(SpendUsageLine.period_start),
        )
        .where(
            SpendUsageLine.organization_id == org_id,
            SpendUsageLine.provider.in_({key.provider for key in keys}),
            SpendUsageLine.api_key_id.in_(ids),
        )
        .group_by(SpendUsageLine.provider, SpendUsageLine.api_key_id)
    )
    return {
        (provider, api_key_id): day.astimezone(UTC)
        for provider, api_key_id, day in rows
        if api_key_id is not None and day is not None
    }
