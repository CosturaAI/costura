"""Sign-in, Google sign-in and `/me` shapes."""

from datetime import datetime

from pydantic import BaseModel

from costura.api.schemas.common import (
    OrganizationOut,
    Role,
)


class DevSignInIn(BaseModel):
    email: str
    name: str | None = None
    secret: str | None = None


class CurrentUserOut(BaseModel):
    email: str
    name: str | None


class SignInOut(BaseModel):
    # The bearer token, shown once; the API stores only its hash.
    token: str
    expires_at: datetime
    user: CurrentUserOut


class GoogleAuthStatusOut(BaseModel):
    enabled: bool
    dev_sign_in_enabled: bool
    operator_sign_in_enabled: bool


class GoogleAuthorizationOut(BaseModel):
    authorization_url: str
    state: str
    nonce: str
    code_verifier: str
    expires_at: datetime


class GoogleCallbackIn(BaseModel):
    code: str
    state: str
    nonce: str
    code_verifier: str


class PendingInvitationOut(BaseModel):
    """An invitation as the person who received it sees it, on `/me` and the join page."""

    id: int
    organization: OrganizationOut
    role: Role
    invited_by: str | None
    expires_at: datetime


class MeOut(BaseModel):
    user: CurrentUserOut
    organizations: list[OrganizationOut]
    # Slug of the read-only sample organization, or null when none has been seeded.
    demo_org: str | None
    # Invitations addressed to this user's e-mail that nobody has claimed yet.
    invitations: list[PendingInvitationOut] = []
