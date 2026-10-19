"""Snapshot Cursor team members.

Cursor has one team directory rather than workspace-scoped member listings. Removed members are
omitted from the active snapshot so an existing row receives `missing_since`; their ids remain
available for historical spend joins.
"""

from typing import Any

from sqlalchemy.orm import Session

from costura.models import ProviderUser
from costura.providers.cursor import PROVIDER
from costura.providers.cursor.client import CursorAdminClient
from costura.providers.normalization import loose_text, text
from costura.providers.records import USER_KIND_SERVICE_ACCOUNT, USER_REPLACE_COLUMNS, UserRecord
from costura.providers.runs import InventorySummary, Target, run_listing

ENDPOINT_MEMBERS = "members"


def users_from_payload(payload: dict[str, Any]) -> list[UserRecord]:
    records: list[UserRecord] = []
    for item in payload.get("teamMembers", []):
        if not isinstance(item, dict) or item.get("isRemoved") is True:
            continue
        external_id = text(item.get("id"), field="id")
        display_name = loose_text(item.get("name"))
        records.append(
            UserRecord(
                external_id=external_id,
                email=loose_text(item.get("email")) or display_name or external_id,
                role=loose_text(item.get("role")) or "member",
                added_at=None,
                provider=PROVIDER,
            )
        )
    return records


def run_inventory_sync(
    session: Session, target: Target, client: CursorAdminClient
) -> list[InventorySummary]:
    members = run_listing(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_MEMBERS,
        pages=client.members_pages,
        normalize=users_from_payload,
        model=ProviderUser,
        constraint="uq_provider_users_external_id",
        replace_columns=USER_REPLACE_COLUMNS,
        missing_exclude=ProviderUser.kind != USER_KIND_SERVICE_ACCOUNT,
    )
    return [members]


__all__ = [
    "run_inventory_sync",
    "users_from_payload",
]
