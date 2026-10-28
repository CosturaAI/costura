"""Organization membership, invitations and role changes."""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from costura.config import Settings
from costura.errors import DomainError, NotFound
from costura.identity_policy import require_email
from costura.models import Organization, OrganizationInvitation, OrganizationMember, User
from costura.models.invitation import INVITATION_DAYS
from costura.models.user import ROLES
from costura.orgs import InvalidRole
from costura.secrets import hash_token
from costura.spend.membership import membership, role_rank


class LastOwner(ValueError, DomainError):
    """The change would leave the organization without an owner."""

    status = 409
    code = "last_owner"

    def __init__(self) -> None:
        super().__init__(
            "this is the last owner of the organization; make someone else an owner first"
        )


class UnknownMember(LookupError, DomainError):
    status = 404
    code = "unknown_member"

    def __init__(self) -> None:
        super().__init__("this person is not a member of the organization")


class AlreadyMember(DomainError):
    status = 409
    code = "already_member"

    def __init__(self, email: str) -> None:
        super().__init__(f"{email} is already a member of the organization")
        self.email = email


class AlreadyInvited(DomainError):
    status = 409
    code = "already_invited"

    def __init__(self, email: str) -> None:
        super().__init__(f"{email} already has a pending invitation")
        self.email = email


class InvitationUnavailable(LookupError, DomainError):
    """The invitation does not exist, was revoked, was accepted or has expired."""

    status = 410
    code = "invitation_unavailable"

    def __init__(self) -> None:
        super().__init__("this invitation is no longer valid; ask an owner for a new one")


def _lock_owners(session: Session, org_id: int) -> None:
    """Serialize role changes and removals in one organization, so two owners demoting each
    other at the same moment cannot both see a second owner and leave none."""
    session.execute(select(Organization.id).where(Organization.id == org_id).with_for_update())


def owner_count(session: Session, org_id: int) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.role == "owner",
            )
        )
        or 0
    )


def set_role(session: Session, org: Organization, user_id: int, role: str) -> OrganizationMember:
    """Change the role of an existing membership. The last owner keeps the role."""
    if role not in ROLES:
        raise InvalidRole(role)
    _lock_owners(session, org.id)
    row = membership(session, org.id, user_id)
    if row is None:
        raise UnknownMember()
    if row.role == role:
        return row
    if row.role == "owner" and owner_count(session, org.id) == 1:
        raise LastOwner()
    row.role = role
    session.flush()
    return row


def remove_member(session: Session, org: Organization, user_id: int) -> None:
    """Remove a membership; the person keeps their account, their sessions and any other
    organization. The last owner cannot be removed, by an owner or by themself."""
    _lock_owners(session, org.id)
    row = membership(session, org.id, user_id)
    if row is None:
        raise UnknownMember()
    if row.role == "owner" and owner_count(session, org.id) == 1:
        raise LastOwner()
    session.delete(row)
    session.flush()


@dataclass(frozen=True)
class Invited:
    """The stored invitation plus the link, which exists only in this response."""

    invitation: OrganizationInvitation
    url: str


def join_url(settings: Settings, token: str) -> str:
    base = (settings.costura_web_public_url or settings.costura_web_origin).rstrip("/")
    return f"{base}/join/{token}"


def is_pending(invitation: OrganizationInvitation, now: datetime) -> bool:
    return (
        invitation.accepted_at is None
        and invitation.revoked_at is None
        and invitation.expires_at > now
    )


def invite(
    session: Session,
    settings: Settings,
    org: Organization,
    email: str,
    role: str,
    invited_by: User,
    *,
    now: datetime | None = None,
) -> Invited:
    """Invite one e-mail address. An address that already belongs to the organization or
    already has a pending invitation is refused, so one address maps to one link."""
    now = now or datetime.now(UTC)
    if role not in ROLES:
        raise InvalidRole(role)
    normalized = require_email(email)
    existing_user = session.scalar(select(User).where(User.email == normalized))
    if existing_user is not None and membership(session, org.id, existing_user.id) is not None:
        raise AlreadyMember(normalized)
    open_row = _open_invitation(session, org.id, normalized)
    if open_row is not None:
        if is_pending(open_row, now):
            raise AlreadyInvited(normalized)
        # An expired invitation holds the pending slot; revoking it frees the address.
        open_row.revoked_at = now
        session.flush()
    token = secrets.token_urlsafe(32)
    row = OrganizationInvitation(
        organization_id=org.id,
        email=normalized,
        role=role,
        token_hash=hash_token(token),
        invited_by=invited_by.id,
        expires_at=now + timedelta(days=INVITATION_DAYS),
    )
    try:
        with session.begin_nested():
            session.add(row)
    except IntegrityError:
        raise AlreadyInvited(normalized) from None
    return Invited(invitation=row, url=join_url(settings, token))


def _open_invitation(session: Session, org_id: int, email: str) -> OrganizationInvitation | None:
    """The row holding the pending slot for this address: neither accepted nor revoked, which
    includes an expired one."""
    return session.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == org_id,
            OrganizationInvitation.email == email,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
        )
    )


def list_invitations(
    session: Session, org_id: int, *, now: datetime | None = None
) -> list[tuple[OrganizationInvitation, User | None]]:
    """Invitations of one organization that nobody accepted or revoked, expired ones
    included, with the user who sent each; by role then e-mail."""
    now = now or datetime.now(UTC)
    rows = session.execute(
        select(OrganizationInvitation, User)
        .outerjoin(User, User.id == OrganizationInvitation.invited_by)
        .where(
            OrganizationInvitation.organization_id == org_id,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
        )
        .order_by(role_rank(OrganizationInvitation.role), OrganizationInvitation.email)
    ).all()
    return [(invitation, user) for invitation, user in rows]


def revoke(
    session: Session, org_id: int, invitation_id: int, *, now: datetime | None = None
) -> OrganizationInvitation:
    """Withdraw a pending invitation; the link stops working."""
    now = now or datetime.now(UTC)
    row = session.get(OrganizationInvitation, invitation_id)
    if row is None or row.organization_id != org_id or row.accepted_at is not None:
        raise InvitationUnavailable()
    if row.revoked_at is None:
        row.revoked_at = now
        session.flush()
    return row


def invitations_for(
    session: Session, user: User, *, now: datetime | None = None
) -> list[tuple[OrganizationInvitation, Organization, User | None]]:
    """Every pending invitation addressed to this user, newest first; what `/me` answers and
    what the join page lists."""
    now = now or datetime.now(UTC)
    rows = session.execute(
        select(OrganizationInvitation, Organization, User)
        .join(Organization, Organization.id == OrganizationInvitation.organization_id)
        .outerjoin(User, User.id == OrganizationInvitation.invited_by)
        .where(
            OrganizationInvitation.email == user.email,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
            OrganizationInvitation.expires_at > now,
        )
        .order_by(OrganizationInvitation.created_at.desc())
    ).all()
    return [(invitation, org, sender) for invitation, org, sender in rows]


def accept(
    session: Session,
    invitation: OrganizationInvitation,
    user: User,
    *,
    now: datetime | None = None,
) -> OrganizationMember:
    """Turn a pending invitation into a membership. The signed-in e-mail must be the invited
    one; an existing membership keeps the higher of the two roles."""
    now = now or datetime.now(UTC)
    if not is_pending(invitation, now):
        raise InvitationUnavailable()
    if invitation.email != user.email:
        raise InvitationUnavailable()
    row = membership(session, invitation.organization_id, user.id)
    if row is None:
        row = OrganizationMember(
            organization_id=invitation.organization_id, user_id=user.id, role=invitation.role
        )
        session.add(row)
    elif ROLES.index(invitation.role) < ROLES.index(row.role):
        row.role = invitation.role
    invitation.accepted_at = now
    session.flush()
    return row


def accept_by_id(
    session: Session, invitation_id: int, user: User, *, now: datetime | None = None
) -> tuple[OrganizationMember, Organization]:
    invitation = session.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.id == invitation_id,
            OrganizationInvitation.email == user.email,
        )
    )
    if invitation is None:
        raise InvitationUnavailable()
    member = accept(session, invitation, user, now=now)
    org = session.get(Organization, invitation.organization_id)
    assert org is not None
    return member, org


def claim(
    session: Session, token: str, user: User, *, now: datetime | None = None
) -> tuple[OrganizationMember, Organization]:
    """Accept the invitation behind a link token."""
    invitation = session.scalar(
        select(OrganizationInvitation).where(OrganizationInvitation.token_hash == hash_token(token))
    )
    if invitation is None:
        raise InvitationUnavailable()
    member = accept(session, invitation, user, now=now)
    org = session.get(Organization, invitation.organization_id)
    assert org is not None
    return member, org


def member_user(session: Session, user_id: int) -> User:
    """The user behind a membership the caller just read or changed."""
    user = session.get(User, user_id)
    if user is None:
        raise NotFound(f"no user {user_id}")
    return user
