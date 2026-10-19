"""Provider inventory and sync run shapes."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from costura.api.schemas.common import RunOut


class RunsOut(BaseModel):
    runs: list[RunOut]
    # The API's clock when it answered; a reader measures the age of the runs against it.
    as_of: datetime | None = None


class ApiKeyOut(BaseModel):
    provider: str
    # The provider account the row came from and its label, for the "Provider - Account"
    # badge; None when the row spans accounts or predates them.
    provider_account_id: int | None = None
    provider_account_label: str | None = None
    external_id: str
    name: str
    partial_key_hint: str | None
    workspace_external_id: str | None
    workspace: str
    created_by_external_id: str | None
    created_by: str
    status: str
    created_at: datetime | None
    expires_at: datetime | None
    last_seen_at: datetime
    missing_since: datetime | None
    missing: bool
    # The e-mail the key's spend counts under in the `person` dimension, and why: "marked" by
    # a member, or "claude_code" for a key Anthropic created for one session. None for a
    # service key.
    person: str | None = None
    person_source: Literal["marked", "claude_code"] | None = None
    last_used_at: datetime | None = None
    last_used_source: Literal["reported", "derived"] | None = None
    principal_type: str | None = None
    scope_type: str | None = None
    limit_reported: bool = False
    spend_limit: str | None = None
    limit_remaining: str | None = None
    limit_reset: str | None = None
    owner: str | None = None
    owner_source: Literal["assigned", "creator", "workspace_admin"] | None = None
    creator_left: bool = False


class WorkspaceOut(BaseModel):
    provider: str
    # The provider account the row came from and its label, for the "Provider - Account"
    # badge; None when the row spans accounts or predates them.
    provider_account_id: int | None = None
    provider_account_label: str | None = None
    external_id: str
    name: str
    archived_at: datetime | None
    admins: list[str]
    api_keys: int
    created_at: datetime | None
    last_seen_at: datetime
    missing_since: datetime | None
    missing: bool


class UserOut(BaseModel):
    provider: str
    external_id: str
    email: str
    role: str
    # "user" or "service_account"; a service account's `email` is its name.
    kind: str
    added_at: datetime | None
    last_seen_at: datetime
    missing_since: datetime | None
    missing: bool
    last_active_at: datetime | None = None
    pending_removal_at: datetime | None = None
    limit_reported: bool = False
    spend_limit: str | None = None


class ApiKeysOut(BaseModel):
    items: list[ApiKeyOut]
    total: int = 0
    limit: int = 0
    offset: int = 0


class WorkspacesOut(BaseModel):
    items: list[WorkspaceOut]
    total: int = 0
    limit: int = 0
    offset: int = 0


class UsersOut(BaseModel):
    items: list[UserOut]
    total: int = 0
    limit: int = 0
    offset: int = 0


class InventorySearchItem(BaseModel):
    """One current inventory resource. A person is one e-mail, so `providers` can list more
    than one connector; every other kind is a single identity."""

    kind: Literal["person", "service", "api_key", "workspace"]
    id: str
    label: str
    providers: list[str]
    provider_account_id: int | None = None
    provider_account_label: str | None = None
    # A display fragment such as a key hint or a role. Never a usable credential.
    hint: str | None = None


class InventorySearchOut(BaseModel):
    items: list[InventorySearchItem]
