"""Organizations, members, invitations, the getting-started card and the entity lookup."""

from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Query, Response

from costura import (
    audit,
    members,
)
from costura.api import schemas
from costura.api.deps import (
    OWNER_ONLY,
    CurrentUserDep,
    OptionalUserDep,
    OrgDep,
    OwnedOrgDep,
    SessionDep,
    SettingsDep,
    WritableOrgDep,
)
from costura.api.guard import VerifiedWriteDep
from costura.api.presenters.common import (
    organization_out,
)
from costura.entities import ENTITY_KINDS, resolve_entity
from costura.models import (
    OrganizationInvitation,
    User,
)
from costura.orgs import (
    clean_name,
    create_org,
    delete_organization,
    ensure_open_slug,
    rename_org,
    visible_orgs,
)
from costura.spend.membership import list_members, membership

router = APIRouter()


@router.get("/orgs", response_model=list[schemas.OrganizationOut])
def orgs(session: SessionDep, user: CurrentUserDep) -> list[schemas.OrganizationOut]:
    """The caller's organizations; the public sample organization and other tenants are not
    listed."""
    return [organization_out(o, role) for o, role in visible_orgs(session, user.id)]


@router.get("/orgs/{org}", response_model=schemas.OrganizationOut)
def organization(
    session: SessionDep, org: OrgDep, user: OptionalUserDep
) -> schemas.OrganizationOut:
    """One organization the caller can open: a membership, or the public sample organization
    (readable without a session, `role` null). 401 without a session elsewhere, 404 when the
    slug is unknown or belongs to another tenant."""
    member = None if user is None else membership(session, org.id, user.id)
    return organization_out(org, None if member is None else member.role)


@router.post("/orgs", response_model=schemas.OrganizationOut, status_code=201)
def create_organization(
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
    body: schemas.OrganizationIn,
    _guard: VerifiedWriteDep,
) -> schemas.OrganizationOut:
    """Create an organization with the caller as its owner. 409 on a taken or reserved slug
    (`COSTURA_ORG`, `demo`, `demo-staging-*`, `demo-retired-*`), 422 on a slug outside
    `^[a-z0-9][a-z0-9-]{1,62}$` or an empty name."""
    ensure_open_slug(body.slug, settings.costura_org)
    org = create_org(session, body.slug, clean_name(body.name), owner=user)
    return organization_out(org, "owner")


@router.patch("/orgs/{org}", response_model=schemas.OrganizationOut)
def rename_organization(
    session: SessionDep,
    org: OwnedOrgDep,
    body: schemas.OrganizationRenameIn,
    _guard: VerifiedWriteDep,
) -> schemas.OrganizationOut:
    """Change the display name (owner only; 403 on the demo organization). The slug is the
    immutable id and is not editable."""
    rename_org(session, org, body.name)
    audit.record("organization_renamed", session=session, org_id=org.id, target=org.slug)
    return organization_out(org, "owner")


@router.get("/orgs/{org}/members", response_model=list[schemas.MemberOut])
def organization_members(
    session: SessionDep, org: OrgDep, user: OptionalUserDep
) -> list[schemas.MemberOut]:
    """People who can open the organization: owners, then members, then viewers, by e-mail
    inside each group. Any member reads it."""
    return [
        schemas.MemberOut(
            id=member_user.id,
            email=member_user.email,
            name=member_user.name,
            role=cast(schemas.Role, member.role),
            created_at=member.created_at,
            is_you=user is not None and member_user.id == user.id,
        )
        for member_user, member in list_members(session, org.id)
    ]


@router.patch("/orgs/{org}/members/{user_id}", response_model=schemas.MemberOut)
def set_member_role(
    session: SessionDep,
    org: OwnedOrgDep,
    user: CurrentUserDep,
    user_id: int,
    body: schemas.MemberRoleIn,
    _guard: VerifiedWriteDep,
) -> schemas.MemberOut:
    """Change one person's role. 404 when they are not a member, 409 when the change would
    leave the organization without an owner (an owner may step down once another one
    exists)."""
    member = members.set_role(session, org, user_id, body.role)
    member_user = members.member_user(session, user_id)
    audit.record(
        "member_role_changed",
        session=session,
        org_id=org.id,
        target=f"user:{user_id}",
        role=member.role,
    )
    return schemas.MemberOut(
        id=member_user.id,
        email=member_user.email,
        name=member_user.name,
        role=cast(schemas.Role, member.role),
        created_at=member.created_at,
        is_you=member_user.id == user.id,
    )


@router.delete("/orgs/{org}/members/{user_id}", status_code=204)
def remove_organization_member(
    session: SessionDep,
    org: WritableOrgDep,
    user: CurrentUserDep,
    user_id: int,
    _guard: VerifiedWriteDep,
) -> Response:
    """Remove a member, or leave the organization by naming yourself. Owners remove anyone;
    everyone else removes only themself (403). 409 on the last owner: the organization would
    become unmanageable. The account, its sessions and its other organizations stay."""
    if user_id != user.id:
        actor = membership(session, org.id, user.id)
        if actor is None or actor.role != "owner":
            raise HTTPException(status_code=403, detail=OWNER_ONLY)
    members.remove_member(session, org, user_id)
    audit.record(
        "member_left" if user_id == user.id else "member_removed",
        session=session,
        org_id=org.id,
        target=f"user:{user_id}",
    )
    return Response(status_code=204)


def _invitation(
    invitation: OrganizationInvitation,
    sender: User | None,
    *,
    now: datetime,
    url: str | None = None,
) -> schemas.InvitationOut:
    return schemas.InvitationOut(
        id=invitation.id,
        email=invitation.email,
        role=cast(schemas.Role, invitation.role),
        invited_by=None if sender is None else sender.email,
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        status="pending" if invitation.expires_at > now else "expired",
        url=url,
    )


@router.get("/orgs/{org}/invitations", response_model=list[schemas.InvitationOut])
def organization_invitations(session: SessionDep, org: OwnedOrgDep) -> list[schemas.InvitationOut]:
    """Invitations nobody has claimed or revoked, expired ones included so an owner can see
    why a link stopped working. Owners only: the list names people outside the organization."""
    now = datetime.now(UTC)
    return [
        _invitation(invitation, sender, now=now)
        for invitation, sender in members.list_invitations(session, org.id)
    ]


@router.post("/orgs/{org}/invitations", response_model=schemas.InvitationOut, status_code=201)
def create_invitation(
    session: SessionDep,
    settings: SettingsDep,
    org: OwnedOrgDep,
    user: CurrentUserDep,
    body: schemas.InvitationIn,
    _guard: VerifiedWriteDep,
) -> schemas.InvitationOut:
    """Invite one e-mail address and answer with the link, which is shown once. The link only
    works for someone signed in with that address. 409 when the address is already a member or
    already invited, 422 when it is not an e-mail."""
    invited = members.invite(session, settings, org, body.email, body.role, user)
    audit.record(
        "invitation_created",
        session=session,
        org_id=org.id,
        target=f"invitation:{invited.invitation.id}",
        role=invited.invitation.role,
    )
    return _invitation(invited.invitation, user, now=datetime.now(UTC), url=invited.url)


@router.delete("/orgs/{org}/invitations/{invitation_id}", status_code=204)
def revoke_invitation(
    session: SessionDep, org: OwnedOrgDep, invitation_id: int, _guard: VerifiedWriteDep
) -> Response:
    """Withdraw an invitation; its link stops working at once. 404 when it was already
    accepted or belongs to another organization."""
    try:
        members.revoke(session, org.id, invitation_id)
    except members.InvitationUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    audit.record(
        "invitation_revoked",
        session=session,
        org_id=org.id,
        target=f"invitation:{invitation_id}",
    )
    return Response(status_code=204)


@router.post("/invitations/{invitation_id}/accept", response_model=schemas.OrganizationOut)
def accept_invitation(
    session: SessionDep, user: CurrentUserDep, invitation_id: int, _guard: VerifiedWriteDep
) -> schemas.OrganizationOut:
    """Join the organization an invitation names. 410 when it is missing, for another
    address, revoked, already used, or expired. The response does not name that address."""
    member, org = members.accept_by_id(session, invitation_id, user)
    audit.record(
        "member_joined", session=session, org_id=org.id, target=f"user:{user.id}", role=member.role
    )
    return organization_out(org, member.role)


@router.post("/invitations/claim", response_model=schemas.OrganizationOut)
def claim_invitation(
    session: SessionDep, user: CurrentUserDep, body: schemas.ClaimIn, _guard: VerifiedWriteDep
) -> schemas.OrganizationOut:
    """Same as accepting, addressed by the token in the join link instead of the id.
    A token for another address answers 410 and does not name that address."""
    member, org = members.claim(session, body.token, user)
    audit.record(
        "member_joined", session=session, org_id=org.id, target=f"user:{user.id}", role=member.role
    )
    return organization_out(org, member.role)


@router.get("/orgs/{org}/entities/{kind}/{entity_id:path}", response_model=schemas.EntityLookupOut)
def entity_lookup(
    session: SessionDep,
    org: OrgDep,
    kind: Annotated[str, Path()],
    entity_id: Annotated[str, Path()],
    scope: Annotated[str | None, Query()] = None,
    account: Annotated[int | None, Query()] = None,
) -> schemas.EntityLookupOut:
    """Which provider an id belongs to.

    `kind` is `key`, `workspace`, `account`, `model` or `anomaly`. The answer comes from the
    inventory tables, from the models each provider has billed, or from the anomaly row. 404
    when nothing matches. A model name that exists under several providers resolves to
    `scope` when it is one of them, else to the provider that billed it most recently.
    `account` selects one provider account when the same external id exists on two consoles
    of a provider."""
    if kind not in ENTITY_KINDS:
        raise HTTPException(status_code=404, detail=f"unknown entity kind {kind!r}")
    owner = resolve_entity(session, org.id, kind, entity_id, scope=scope, account=account)
    if owner is None:
        label = "anomaly" if kind == "anomaly" else f"{kind} {entity_id!r}"
        raise HTTPException(status_code=404, detail=f"unknown {label}")
    return schemas.EntityLookupOut(
        provider=owner.provider, provider_account_id=owner.provider_account_id
    )


@router.delete("/orgs/{org}", status_code=204)
def delete_org(
    session: SessionDep,
    org: OwnedOrgDep,
    body: schemas.OrganizationDeleteIn,
    _guard: VerifiedWriteDep,
) -> Response:
    """Delete the organization when the body slug matches. 409 while a sync is queued or
    running. 422 when the confirmation does not match."""
    if body.slug != org.slug:
        raise HTTPException(status_code=422, detail="confirmation slug does not match")
    delete_organization(session, org, confirm_slug=body.slug)
    audit.record("organization_deleted", session=session, org_id=org.id, target=org.slug)
    return Response(status_code=204)
