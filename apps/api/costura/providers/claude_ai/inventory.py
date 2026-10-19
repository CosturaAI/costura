"""Snapshot users returned by Claude.ai Enterprise Analytics."""

from typing import Any

from sqlalchemy import false
from sqlalchemy.orm import Session

from costura.models import ProviderUser
from costura.providers.claude_ai import PROVIDER
from costura.providers.claude_ai.client import ClaudeAiAnalyticsClient
from costura.providers.normalization import optional_day, text
from costura.providers.records import USER_REPLACE_COLUMNS, UserRecord
from costura.providers.runs import InventorySummary, Target, run_listing

ENDPOINT_USERS = "analytics_users"


def users_from_payload(payload: dict[str, Any]) -> list[UserRecord]:
    records: list[UserRecord] = []
    for item in payload.get("data", []):
        user = item.get("user")
        if not isinstance(user, dict):
            continue
        records.append(
            UserRecord(
                provider=PROVIDER,
                external_id=text(user.get("id"), field="user.id"),
                email=text(user.get("email_address"), field="user.email_address"),
                role="member",
                added_at=None,
                last_active_at=optional_day(
                    item.get("last_activity_date"), field="last_activity_date"
                ),
            )
        )
    return records


def run_inventory_sync(
    session: Session, target: Target, client: ClaudeAiAnalyticsClient
) -> list[InventorySummary]:
    return [
        run_listing(
            session,
            target,
            PROVIDER,
            endpoint=ENDPOINT_USERS,
            pages=client.users_pages,
            normalize=users_from_payload,
            model=ProviderUser,
            constraint="uq_provider_users_external_id",
            replace_columns=USER_REPLACE_COLUMNS,
            missing_exclude=false(),
        )
    ]


__all__ = ["run_inventory_sync", "users_from_payload"]
