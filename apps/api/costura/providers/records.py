"""Inventory records every provider normalizes into. The field helpers that validate listing
payloads are in `costura.providers.normalization`."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

USER_KIND_USER = "user"
USER_KIND_SERVICE_ACCOUNT = "service_account"


@dataclass(frozen=True)
class WorkspaceRecord:
    external_id: str
    name: str
    created_at: datetime | None
    archived_at: datetime | None
    tags: dict[str, str]
    provider: str


@dataclass(frozen=True)
class UserRecord:
    external_id: str
    email: str
    role: str
    added_at: datetime | None
    provider: str
    # "user" or "service_account"; a service account carries its name in `email`.
    kind: str = USER_KIND_USER
    last_active_at: datetime | None = None
    pending_removal_at: datetime | None = None
    limit_reported: bool = False
    spend_limit: Decimal | None = None


@dataclass(frozen=True)
class ApiKeyRecord:
    external_id: str
    name: str
    partial_key_hint: str | None
    workspace_external_id: str | None
    created_at: datetime | None
    created_by_external_id: str | None
    principal_external_id: str | None
    status: str
    expires_at: datetime | None
    provider: str
    last_used_at: datetime | None = None
    principal_type: str | None = None
    scope_type: str | None = None
    limit_reported: bool = False
    spend_limit: Decimal | None = None
    limit_remaining: Decimal | None = None
    limit_reset: str | None = None


@dataclass(frozen=True)
class MemberRecord:
    workspace_external_id: str
    user_external_id: str
    role: str
    provider: str


@dataclass(frozen=True)
class LimitRecord:
    external_id: str
    scope_kind: str
    scope_name: str | None
    product: str | None
    amount: Decimal
    consumed: Decimal | None
    enforcement: str
    provider: str


LIMIT_REPLACE_COLUMNS = ("scope_kind", "scope_name", "product", "amount", "consumed", "enforcement")

USER_REPLACE_COLUMNS = (
    "email",
    "role",
    "added_at",
    "kind",
    "last_active_at",
    "pending_removal_at",
    "limit_reported",
    "spend_limit",
)

API_KEY_REPLACE_COLUMNS = (
    "name",
    "partial_key_hint",
    "workspace_external_id",
    "created_at",
    "created_by_external_id",
    "principal_external_id",
    "status",
    "expires_at",
    "last_used_at",
    "principal_type",
    "scope_type",
    "limit_reported",
    "spend_limit",
    "limit_remaining",
    "limit_reset",
)
