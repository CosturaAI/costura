"""Snapshot OpenAI's directory: projects, organization users, project API keys and project
members.

Same semantics as the other inventories: one run
per listing, raw pages kept, rows upserted by external id, rows no longer listed marked
`missing_since`. Keys and members are listed project by project; a project the admin key
cannot read (403, 404) is recorded as skipped instead of failing the run, and its rows are not
marked missing.

Mapping: project -> `provider_workspaces` (`archived_at` kept, `status` in tags), user ->
`provider_users` (`kind="user"`), project key -> `provider_api_keys` (hint = the tail of
`redacted_value`, `created_by` = the owning user or service account id), the service accounts
that own keys -> `provider_users` (`kind="service_account"`, the name in `email`; the users
listing does not return them), project user -> `provider_workspace_members`. Timestamps are
Unix seconds.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from costura.db import Base
from costura.models import (
    ProviderApiKey,
    ProviderUser,
    ProviderWorkspace,
    ProviderWorkspaceMember,
)
from costura.providers.lines import NormalizeError
from costura.providers.normalization import loose_text, text
from costura.providers.openai import PROVIDER
from costura.providers.openai.client import FetchedPage, OpenAIAdminClient
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

ENDPOINT_PROJECTS = "projects"
ENDPOINT_USERS = "users"
ENDPOINT_API_KEYS = "project_api_keys"
ENDPOINT_SERVICE_ACCOUNTS = "service_accounts"
ENDPOINT_PROJECT_USERS = "project_users"

SKIPPABLE_PROJECT_STATUSES = frozenset({400, 403, 404})
STATUS_ACTIVE = "active"
HINT_LENGTH = 4


def unix_timestamp(value: Any, *, field: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NormalizeError(f"{field} is not a Unix timestamp: {value!r}")
    return datetime.fromtimestamp(int(value), tz=UTC)


def projects_from_payload(payload: dict[str, Any]) -> list[WorkspaceRecord]:
    records = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        archived_at = unix_timestamp(item.get("archived_at"), field="archived_at")
        status = loose_text(item.get("status"))
        records.append(
            WorkspaceRecord(
                external_id=text(item.get("id"), field="id"),
                name=text(item.get("name"), field="name"),
                created_at=unix_timestamp(item.get("created_at"), field="created_at"),
                archived_at=archived_at,
                tags={"status": status} if status else {},
                provider=PROVIDER,
            )
        )
    return records


def users_from_payload(payload: dict[str, Any]) -> list[UserRecord]:
    records = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        user_id = text(item.get("id"), field="id")
        records.append(
            UserRecord(
                external_id=user_id,
                email=loose_text(item.get("email")) or user_id,
                role=loose_text(item.get("role")) or "member",
                added_at=unix_timestamp(item.get("added_at"), field="added_at"),
                provider=PROVIDER,
                kind=USER_KIND_USER,
            )
        )
    return records


def key_owner(owner: Any) -> tuple[str | None, dict[str, Any] | None]:
    """`(type, holder)` of a project key's owner: `("user", {...})`,
    `("service_account", {...})`, or `(None, None)`."""
    if not isinstance(owner, dict):
        return None, None
    kind = loose_text(owner.get("type"))
    holder = owner.get(kind) if kind else None
    if isinstance(holder, dict):
        return kind, holder
    return None, None


def key_owner_id(owner: Any) -> str | None:
    """Id of the user or service account that owns a project key."""
    _, holder = key_owner(owner)
    return loose_text(holder.get("id")) if holder else None


def service_accounts_from_payload(payload: dict[str, Any], *, project_id: str) -> list[UserRecord]:
    """The service accounts owning keys on one project keys page, as inventory users; the
    usage report names them in `user_id` and the users listing never returns them."""
    records: list[UserRecord] = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        kind, holder = key_owner(item.get("owner"))
        if kind != USER_KIND_SERVICE_ACCOUNT or holder is None:
            continue
        account_id = loose_text(holder.get("id"))
        if account_id is None:
            continue
        records.append(
            UserRecord(
                external_id=account_id,
                email=loose_text(holder.get("name")) or account_id,
                role=loose_text(holder.get("role")) or "member",
                added_at=unix_timestamp(holder.get("created_at"), field="created_at"),
                provider=PROVIDER,
                kind=USER_KIND_SERVICE_ACCOUNT,
            )
        )
    return records


def key_hint(redacted_value: Any) -> str | None:
    value = loose_text(redacted_value)
    if value is None:
        return None
    tail = value.rsplit(".", 1)[-1][-HINT_LENGTH:]
    return tail or None


def api_keys_from_payload(payload: dict[str, Any], *, project_id: str) -> list[ApiKeyRecord]:
    records = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        owner_id = key_owner_id(item.get("owner"))
        records.append(
            ApiKeyRecord(
                external_id=text(item.get("id"), field="id"),
                name=loose_text(item.get("name")) or text(item.get("id"), field="id"),
                partial_key_hint=key_hint(item.get("redacted_value")),
                workspace_external_id=project_id,
                created_at=unix_timestamp(item.get("created_at"), field="created_at"),
                created_by_external_id=owner_id,
                principal_external_id=owner_id,
                status=STATUS_ACTIVE,
                expires_at=unix_timestamp(item.get("expires_at"), field="expires_at"),
                provider=PROVIDER,
                last_used_at=unix_timestamp(item.get("last_used_at"), field="last_used_at"),
            )
        )
    return records


def members_from_payload(payload: dict[str, Any], *, project_id: str) -> list[MemberRecord]:
    return [
        MemberRecord(
            workspace_external_id=project_id,
            user_external_id=text(item.get("id"), field="id"),
            role=loose_text(item.get("role")) or "member",
            provider=PROVIDER,
        )
        for item in payload.get("data", [])
        if isinstance(item, dict)
    ]


def run_inventory_sync(
    session: Session, target: Target, client: OpenAIAdminClient
) -> list[InventorySummary]:
    """Projects, users, then keys and members of every known project."""
    return [
        run_listing(
            session,
            target,
            PROVIDER,
            endpoint=ENDPOINT_PROJECTS,
            pages=client.projects_pages,
            normalize=projects_from_payload,
            model=ProviderWorkspace,
            constraint="uq_provider_workspaces_external_id",
            replace_columns=("name", "created_at", "archived_at", "tags"),
        ),
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
            missing_exclude=ProviderUser.kind != USER_KIND_SERVICE_ACCOUNT,
        ),
        _run_per_project(
            session,
            target,
            client,
            endpoint=ENDPOINT_API_KEYS,
            pages=client.project_api_keys_pages,
            normalize=api_keys_from_payload,
            model=ProviderApiKey,
            constraint="uq_provider_api_keys_external_id",
            replace_columns=API_KEY_REPLACE_COLUMNS,
        ),
        _run_per_project(
            session,
            target,
            client,
            endpoint=ENDPOINT_SERVICE_ACCOUNTS,
            pages=client.project_api_keys_pages,
            normalize=service_accounts_from_payload,
            model=ProviderUser,
            constraint="uq_provider_users_external_id",
            replace_columns=USER_REPLACE_COLUMNS,
            missing_scope=ProviderUser.kind == USER_KIND_SERVICE_ACCOUNT,
        ),
        _run_per_project(
            session,
            target,
            client,
            endpoint=ENDPOINT_PROJECT_USERS,
            pages=client.project_users_pages,
            normalize=members_from_payload,
            model=ProviderWorkspaceMember,
            constraint="uq_provider_workspace_members_workspace_user",
            replace_columns=("role",),
        ),
    ]


def _project_ids(session: Session, target: Target) -> list[str]:
    return list(
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


def _missing_exclude(model: type[Base], base: Any) -> Any:
    """A skipped project drops out of the missing-row pass. Service accounts are not tied to
    one project, so a skipped project keeps every one of their rows."""

    def exclude(skipped: Sequence[str]) -> Any:
        if not skipped:
            return base
        if hasattr(model.__table__.c, "workspace_external_id"):
            return model.__table__.c.workspace_external_id.not_in(skipped)
        return false()

    return exclude


def _run_per_project(
    session: Session,
    target: Target,
    client: OpenAIAdminClient,
    *,
    endpoint: str,
    pages: Any,
    normalize: Any,
    model: type[Base],
    constraint: str,
    replace_columns: tuple[str, ...],
    missing_scope: Any = None,
) -> InventorySummary:
    """One run over every project: the listing is per project on the Admin API, so the run
    concatenates them and stores each page with the project id it was fetched for.
    `missing_scope` narrows the rows this run may mark missing (service accounts share the
    users table with the organization users listing)."""
    return run_scoped_listing(
        session,
        target,
        PROVIDER,
        endpoint=endpoint,
        scopes=_project_ids(session, target),
        pages=pages,
        normalize=lambda payload, project_id: normalize(payload, project_id=project_id),
        scope_param="project_id",
        model=model,
        constraint=constraint,
        replace_columns=replace_columns,
        options=ScopedListingOptions(
            skippable_statuses=SKIPPABLE_PROJECT_STATUSES,
            page_factory=FetchedPage,
            missing_exclude=_missing_exclude(model, missing_scope),
        ),
    )


__all__ = [
    "api_keys_from_payload",
    "key_hint",
    "key_owner",
    "key_owner_id",
    "members_from_payload",
    "projects_from_payload",
    "run_inventory_sync",
    "service_accounts_from_payload",
    "users_from_payload",
]
