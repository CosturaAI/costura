"""Snapshot Anthropic's directory (workspaces, users, API keys, workspace members).

One `provider_sync_runs` row per listing, raw pages kept, rows upserted by external id, and
rows no longer returned by a complete listing marked `missing_since`.
"""

from collections.abc import Callable, Iterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.db import Base
from costura.models import ProviderApiKey, ProviderUser, ProviderWorkspace, ProviderWorkspaceMember
from costura.providers.anthropic import PROVIDER
from costura.providers.anthropic.client import AnthropicAdminClient, FetchedPage
from costura.providers.lines import NormalizeError
from costura.providers.normalization import loose_text, nested_id, optional_timestamp, text
from costura.providers.records import (
    API_KEY_REPLACE_COLUMNS,
    USER_KIND_SERVICE_ACCOUNT,
    USER_KIND_USER,
    USER_REPLACE_COLUMNS,
    ApiKeyRecord,
    MemberRecord,
    UserRecord,
    WorkspaceRecord,
)
from costura.providers.runs import (
    InventorySummary,
    ScopedListingOptions,
    Target,
    run_listing,
    run_scoped_listing,
)

ENDPOINT_WORKSPACES = "workspaces"
ENDPOINT_USERS = "users"
ENDPOINT_API_KEYS = "api_keys"
ENDPOINT_WORKSPACE_MEMBERS = "workspace_members"

# Archived or otherwise unreadable workspaces answer with a definitive client error on the
# members listing; that workspace is skipped and the run continues.
SKIPPABLE_MEMBER_STATUSES = frozenset({400, 403, 404})


def workspaces_from_payload(payload: dict[str, Any]) -> list[WorkspaceRecord]:
    records = []
    for item in payload.get("data", []):
        tags = item.get("tags") or {}
        records.append(
            WorkspaceRecord(
                provider=PROVIDER,
                external_id=text(item.get("id"), field="id"),
                name=text(item.get("name"), field="name"),
                created_at=optional_timestamp(item.get("created_at"), field="created_at"),
                archived_at=optional_timestamp(item.get("archived_at"), field="archived_at"),
                tags={k: v for k, v in tags.items() if isinstance(v, str)},
            )
        )
    return records


def users_from_payload(payload: dict[str, Any]) -> list[UserRecord]:
    return [
        UserRecord(
            provider=PROVIDER,
            external_id=text(item.get("id"), field="id"),
            email=text(item.get("email"), field="email"),
            role=text(item.get("role"), field="role"),
            added_at=optional_timestamp(item.get("added_at"), field="added_at"),
        )
        for item in payload.get("data", [])
    ]


def api_keys_from_payload(payload: dict[str, Any]) -> list[ApiKeyRecord]:
    return [
        ApiKeyRecord(
            provider=PROVIDER,
            external_id=text(item.get("id"), field="id"),
            name=text(item.get("name"), field="name"),
            partial_key_hint=loose_text(item.get("partial_key_hint")),
            workspace_external_id=loose_text(item.get("workspace_id")),
            created_at=optional_timestamp(item.get("created_at"), field="created_at"),
            created_by_external_id=nested_id(item.get("created_by")),
            principal_external_id=principal_id(item.get("principal")),
            status=text(item.get("status"), field="status"),
            expires_at=optional_timestamp(item.get("expires_at"), field="expires_at"),
            principal_type=principal_type(item.get("principal")),
            scope_type=loose_text(item["scope"].get("type"))
            if isinstance(item.get("scope"), dict)
            else None,
        )
        for item in payload.get("data", [])
    ]


PRINCIPAL_TYPES = {
    "user": USER_KIND_USER,
    "user_actor": USER_KIND_USER,
    "service_account": USER_KIND_SERVICE_ACCOUNT,
    "service_account_actor": USER_KIND_SERVICE_ACCOUNT,
}


def principal_id(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    return (
        loose_text(value.get("user_id"))
        or loose_text(value.get("service_account_id"))
        or loose_text(value.get("id"))
    )


def principal_type(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    return PRINCIPAL_TYPES.get(loose_text(value.get("type")) or "")


def members_from_payload(payload: dict[str, Any], *, workspace_id: str) -> list[MemberRecord]:
    records = []
    for item in payload.get("data", []):
        returned = loose_text(item.get("workspace_id"))
        if returned is not None and returned != workspace_id:
            raise NormalizeError(f"member of {returned} returned while listing {workspace_id}")
        records.append(
            MemberRecord(
                provider=PROVIDER,
                workspace_external_id=workspace_id,
                user_external_id=text(item.get("user_id"), field="user_id"),
                role=text(item.get("workspace_role"), field="workspace_role"),
            )
        )
    return records


def run_inventory_sync(
    session: Session, target: Target, client: AnthropicAdminClient
) -> list[InventorySummary]:
    """Workspaces, users, API keys, then members of every known workspace."""
    summaries = [
        _run_listing(
            session,
            target,
            endpoint=ENDPOINT_WORKSPACES,
            pages=client.workspaces_pages,
            normalize=workspaces_from_payload,
            model=ProviderWorkspace,
            constraint="uq_provider_workspaces_external_id",
            replace_columns=("name", "created_at", "archived_at", "tags"),
        ),
        _run_listing(
            session,
            target,
            endpoint=ENDPOINT_USERS,
            pages=client.users_pages,
            normalize=users_from_payload,
            model=ProviderUser,
            constraint="uq_provider_users_external_id",
            replace_columns=USER_REPLACE_COLUMNS,
        ),
        _run_listing(
            session,
            target,
            endpoint=ENDPOINT_API_KEYS,
            pages=client.api_keys_pages,
            normalize=api_keys_from_payload,
            model=ProviderApiKey,
            constraint="uq_provider_api_keys_external_id",
            replace_columns=API_KEY_REPLACE_COLUMNS,
        ),
    ]
    summaries.append(_run_members(session, target, client))
    return summaries


def _run_listing[RecordT](
    session: Session,
    target: Target,
    *,
    endpoint: str,
    pages: Callable[[], Iterator[FetchedPage]],
    normalize: Callable[[dict[str, Any]], list[RecordT]],
    model: type[Base],
    constraint: str,
    replace_columns: tuple[str, ...],
) -> InventorySummary:
    return run_listing(
        session,
        target,
        PROVIDER,
        endpoint=endpoint,
        pages=pages,
        normalize=normalize,
        model=model,
        constraint=constraint,
        replace_columns=replace_columns,
    )


def _run_members(
    session: Session, target: Target, client: AnthropicAdminClient
) -> InventorySummary:
    workspace_ids = list(
        session.scalars(
            select(ProviderWorkspace.external_id)
            .where(
                ProviderWorkspace.provider_account_id == target.account_id,
                ProviderWorkspace.provider == PROVIDER,
                ProviderWorkspace.missing_since.is_(None),
            )
            .order_by(ProviderWorkspace.external_id)
        )
    )
    return run_scoped_listing(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_WORKSPACE_MEMBERS,
        scopes=workspace_ids,
        pages=client.workspace_members_pages,
        normalize=lambda payload, workspace_id: members_from_payload(
            payload, workspace_id=workspace_id
        ),
        scope_param="workspace_id",
        model=ProviderWorkspaceMember,
        constraint="uq_provider_workspace_members_workspace_user",
        replace_columns=("role",),
        options=ScopedListingOptions(
            skippable_statuses=SKIPPABLE_MEMBER_STATUSES,
            page_factory=FetchedPage,
            missing_exclude=lambda skipped: (
                ProviderWorkspaceMember.workspace_external_id.not_in(skipped) if skipped else None
            ),
        ),
    )
