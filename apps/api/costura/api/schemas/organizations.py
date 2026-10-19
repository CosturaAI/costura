"""Organization, member, invitation, getting-started and entity-lookup shapes."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from costura.api.schemas.common import (
    ProviderOut,
    Role,
    SchedulerRunStatus,
    SchedulerTrigger,
    SyncStepOut,
)


class OrganizationIn(BaseModel):
    name: str
    slug: str


class OrganizationRenameIn(BaseModel):
    name: str


class EntityLookupOut(BaseModel):
    """Which provider (and, once accounts exist, which account) an entity id belongs to."""

    provider: str
    provider_account_id: int | None = None


class InvitationOut(BaseModel):
    id: int
    email: str
    role: Role
    # E-mail of the owner who sent it, or null when that account is gone.
    invited_by: str | None
    created_at: datetime
    expires_at: datetime
    # `expired` is derived from `expires_at`; a settled invitation is never listed.
    status: Literal["pending", "expired"]
    # The join link, returned only in the response that created the invitation.
    url: str | None = None


class MemberOut(BaseModel):
    # `users.id`; the member routes address a person by it, since an e-mail can change.
    id: int
    email: str
    name: str | None
    role: Role
    created_at: datetime
    # True on the caller's own row, so the client can label it and keep the last owner safe.
    is_you: bool = False


class MemberRoleIn(BaseModel):
    role: Role


class InvitationIn(BaseModel):
    email: str
    role: Role


class ClaimIn(BaseModel):
    token: str


class SchedulerRunOut(BaseModel):
    id: int
    provider: str
    # The provider account the row came from and its label, for the "Provider - Account"
    # badge; None when the row spans accounts or predates them.
    provider_account_id: int | None = None
    provider_account_label: str | None = None
    trigger: SchedulerTrigger
    status: SchedulerRunStatus
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    steps: list[SyncStepOut]


class SetupOut(BaseModel):
    """First-run state of an organization: `connect` while no provider is connected, `ready`
    once a month has cost lines, `syncing` in between, `needs_pricing` when Codex is connected
    and has no credit price yet."""

    state: str  # "connect", "syncing", "ready" or "needs_pricing"
    providers: list[ProviderOut]
    runs: list[SchedulerRunOut]  # latest scheduler run per provider, any trigger
    first_month: str | None  # newest month with cost lines across every provider
    dismissed_at: datetime | None
    writes_enabled: bool
    # Newest worker heartbeat, so the banner can tell "no worker" from "lock busy".
    worker_seen_at: datetime | None = None
    # False when COSTURA_SECRET_KEY is absent and the browser cannot store a key.
    secret_ready: bool = True
    # True when a connected Codex account has no credit price.
    needs_pricing: bool = False


class OrganizationDeleteIn(BaseModel):
    """The slug typed by the owner. It must match the organization in the path."""

    slug: str
