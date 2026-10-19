"""Snapshot OpenRouter's directory: workspaces, API keys, and, for organization accounts,
organization members and workspace members.

Same semantics as the Anthropic inventory: one run per listing, raw pages kept,
rows upserted by external id, rows no longer listed marked
`missing_since`. Personal accounts answer 404 on `/organization/members` and 403 on
`/workspaces/{id}/members`; those listings are recorded as skipped instead of failing the run.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import (
    ProviderApiKey,
    ProviderUser,
    ProviderWorkspace,
    ProviderWorkspaceMember,
)
from costura.providers.normalization import (
    loose_text,
    optional_decimal,
    optional_timestamp,
    text,
)
from costura.providers.openrouter import PROVIDER
from costura.providers.openrouter.client import (
    FetchedPage,
    OpenRouterApiError,
    OpenRouterManagementClient,
)
from costura.providers.records import (
    API_KEY_REPLACE_COLUMNS,
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
    close_inventory_run,
    mark_missing,
    open_run,
    run_listing,
    run_scoped_listing,
    store_page,
    write_records,
)

ENDPOINT_WORKSPACES = "workspaces"
ENDPOINT_USERS = "organization_members"
ENDPOINT_API_KEYS = "keys"
ENDPOINT_WORKSPACE_MEMBERS = "workspace_members"

# Personal (non-organization) accounts: definitive client errors on the member listings.
SKIPPABLE_MEMBER_STATUSES = frozenset({400, 403, 404})
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"


def workspaces_from_payload(payload: dict[str, Any]) -> list[WorkspaceRecord]:
    return [
        WorkspaceRecord(
            external_id=text(item.get("id"), field="id"),
            name=text(item.get("name"), field="name"),
            created_at=optional_timestamp(item.get("created_at"), field="created_at"),
            archived_at=None,
            tags={"slug": item["slug"]} if isinstance(item.get("slug"), str) else {},
            provider=PROVIDER,
        )
        for item in payload.get("data", [])
        if isinstance(item, dict)
    ]


def api_keys_from_payload(payload: dict[str, Any]) -> list[ApiKeyRecord]:
    return [
        ApiKeyRecord(
            external_id=text(item.get("hash"), field="hash"),
            name=text(item.get("name"), field="name"),
            partial_key_hint=loose_text(item.get("label")),
            workspace_external_id=loose_text(item.get("workspace_id")),
            created_at=optional_timestamp(item.get("created_at"), field="created_at"),
            created_by_external_id=loose_text(item.get("creator_user_id")),
            principal_external_id=None,
            status=STATUS_DISABLED if item.get("disabled") is True else STATUS_ACTIVE,
            expires_at=optional_timestamp(item.get("expires_at"), field="expires_at"),
            provider=PROVIDER,
            last_used_at=optional_timestamp(item.get("last_used_at"), field="last_used_at"),
            limit_reported=True,
            spend_limit=optional_decimal(item.get("limit"), field="limit"),
            limit_remaining=optional_decimal(item.get("limit_remaining"), field="limit_remaining"),
            limit_reset=loose_text(item.get("limit_reset")),
        )
        for item in payload.get("data", [])
        if isinstance(item, dict)
    ]


def users_from_payload(payload: dict[str, Any]) -> list[UserRecord]:
    records = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        user_id = loose_text(item.get("user_id")) or text(item.get("id"), field="id")
        records.append(
            UserRecord(
                external_id=user_id,
                email=loose_text(item.get("email")) or user_id,
                role=loose_text(item.get("role")) or "member",
                added_at=optional_timestamp(item.get("created_at"), field="created_at"),
                provider=PROVIDER,
            )
        )
    return records


def members_from_payload(payload: dict[str, Any], *, workspace_id: str) -> list[MemberRecord]:
    records = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        user_id = loose_text(item.get("user_id")) or text(item.get("id"), field="id")
        records.append(
            MemberRecord(
                workspace_external_id=workspace_id,
                user_external_id=user_id,
                role=loose_text(item.get("role")) or "member",
                provider=PROVIDER,
            )
        )
    return records


def run_inventory_sync(
    session: Session, target: Target, client: OpenRouterManagementClient
) -> list[InventorySummary]:
    """Workspaces, organization members, API keys, then members of every known workspace."""
    summaries = [
        run_listing(
            session,
            target,
            PROVIDER,
            endpoint=ENDPOINT_WORKSPACES,
            pages=client.workspaces_pages,
            normalize=workspaces_from_payload,
            model=ProviderWorkspace,
            constraint="uq_provider_workspaces_external_id",
            replace_columns=("name", "created_at", "archived_at", "tags"),
        ),
        _run_users(session, target, client),
        run_listing(
            session,
            target,
            PROVIDER,
            endpoint=ENDPOINT_API_KEYS,
            pages=client.keys_pages,
            normalize=api_keys_from_payload,
            model=ProviderApiKey,
            constraint="uq_provider_api_keys_external_id",
            replace_columns=API_KEY_REPLACE_COLUMNS,
        ),
        _run_members(session, target, client),
    ]
    return summaries


def _run_users(
    session: Session, target: Target, client: OpenRouterManagementClient
) -> InventorySummary:
    """Organization members, or an empty succeeded run when the account is personal. Users
    then come only from the keys' `creator_user_id`, which the resolver labels by id."""
    run = open_run(session, target, PROVIDER, ENDPOINT_USERS)
    summary = InventorySummary(endpoint=ENDPOINT_USERS, run_id=run.id)
    try:
        records: list[UserRecord] = []
        try:
            for page in client.organization_members_pages():
                store_page(session, run, page)
                summary.pages_fetched += 1
                summary.items += len(page.items)
                records.extend(users_from_payload(page.payload))
        except OpenRouterApiError as exc:
            if exc.status_code not in SKIPPABLE_MEMBER_STATUSES:
                raise
            summary.skipped_workspaces.append("organization")
            close_inventory_run(session, run, summary, None)
            return summary
        summary.rows_upserted = write_records(
            session,
            ProviderUser,
            records,
            target,
            run.id,
            constraint="uq_provider_users_external_id",
            replace_columns=USER_REPLACE_COLUMNS,
        )
        mark_missing(session, ProviderUser, target, PROVIDER, run.id)
    except Exception as exc:
        session.rollback()
        close_inventory_run(session, run, summary, exc)
        raise
    close_inventory_run(session, run, summary, None)
    return summary


def _run_members(
    session: Session, target: Target, client: OpenRouterManagementClient
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


__all__ = [
    "api_keys_from_payload",
    "members_from_payload",
    "run_inventory_sync",
    "users_from_payload",
    "workspaces_from_payload",
]
