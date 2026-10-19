"""Who to contact about an anomaly, derived from the inventory the provider already exposes.

An OAuth account is a person; an API key names the person who created it and belongs to a
workspace with administrators; the organization total has no person of its own, so its
owners are the owners of the principals ranked under its root causes. The Costura
organization owners close every list as a fallback, so the page never shows an empty card;
when the provider inventory names nobody, `owners_gap` says why, so the fallback is never read
as the person who caused the spend. Nothing here is stored: the answer follows the current
inventory snapshot.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import OwnerAssignment, SpendAnomaly
from costura.spend.dimensions import KEY_DEFAULT_WORKSPACE
from costura.spend.inventory import NOT_IN_INVENTORY, InventoryResolver
from costura.spend.membership import list_members

ASSIGNED = "assigned in Costura"
KEY_CREATOR = "created the key"
ACCOUNT_USER = "used their own login"
WORKSPACE_ADMIN = "workspace admin"
ORGANIZATION_OWNER = "organization owner"
COSTURA_SOURCE = "Costura organization"


@dataclass(frozen=True)
class Owner:
    email: str
    # One of `ASSIGNED`, `KEY_CREATOR`, `ACCOUNT_USER`, `WORKSPACE_ADMIN`, `ORGANIZATION_OWNER`.
    role: str
    # The key or workspace that led to this person, or `COSTURA_SOURCE`.
    source: str
    # The free-text note of an assignment; None for owners read from the inventory.
    note: str | None = None


# (kind, external_id) -> assignment, for one organization and provider.
Assignments = dict[tuple[str, str], OwnerAssignment]


def load_assignments(session: Session, org_id: int, provider: str) -> Assignments:
    rows = session.scalars(
        select(OwnerAssignment).where(
            OwnerAssignment.organization_id == org_id, OwnerAssignment.provider == provider
        )
    )
    return {(row.kind, row.external_id): row for row in rows}


def organization_owners(session: Session, org_id: int) -> list[Owner]:
    """The Costura owners of the organization, the fallback contact on every anomaly."""
    return [
        Owner(email=user.email, role=ORGANIZATION_OWNER, source=COSTURA_SOURCE)
        for user, member in list_members(session, org_id)
        if member.role == "owner"
    ]


def anomaly_owners(
    resolver: InventoryResolver,
    row: SpendAnomaly,
    org_owners: list[Owner],
    assignments: Assignments | None = None,
) -> list[Owner]:
    """Owners of one anomaly, most specific first, one entry per e-mail: the contact assigned
    in Costura to the key or its workspace, then the inventory's people, then `org_owners`
    (from `organization_owners`)."""
    assignments = assignments or {}
    owners: list[Owner] = []
    if row.series_kind == "api_key":
        owners.extend(key_owners(resolver, row.provider, row.series_id, assignments))
    elif row.series_kind == "account":
        owners.extend(account_owners(resolver, row.provider, row.series_id))
    else:
        for cause in row.root_causes:
            kind, cause_id = str(cause["kind"]), str(cause["id"])
            if kind == "api_key":
                owners.extend(key_owners(resolver, row.provider, cause_id, assignments))
            elif kind == "account":
                owners.extend(account_owners(resolver, row.provider, cause_id))
    owners.extend(org_owners)
    return _dedupe(owners)


def assigned_owner(
    assignments: Assignments, kind: str, external_id: str, label: str
) -> Owner | None:
    row = assignments.get((kind, external_id))
    if row is None:
        return None
    return Owner(email=row.email, role=ASSIGNED, source=label, note=row.note)


def account_owners(resolver: InventoryResolver, provider: str, account_id: str) -> list[Owner]:
    """The person behind an OAuth login, when the member list knows the id."""
    email = resolver.user_email(provider, account_id)
    if not _known(email):
        return []
    return [Owner(email=email, role=ACCOUNT_USER, source=f"login {account_id}")]


def key_owners(
    resolver: InventoryResolver,
    provider: str,
    api_key_id: str,
    assignments: Assignments | None = None,
) -> list[Owner]:
    """The contact assigned to the key, the key's creator, then the assigned contact and the
    administrators of its workspace. A key outside the inventory still has its assignment."""
    assignments = assignments or {}
    label = resolver.api_key_label(provider, api_key_id)
    owners: list[Owner] = []
    assigned = assigned_owner(assignments, "api_key", api_key_id, label)
    if assigned is not None:
        owners.append(assigned)
    info = resolver.api_key(provider, api_key_id)
    if info is None:
        return owners
    creator = resolver.user_email(provider, info.created_by_external_id)
    if _known(creator):
        owners.append(Owner(email=creator, role=KEY_CREATOR, source=label))
    if info.workspace_external_id is not None:
        owners.extend(workspace_owners(resolver, provider, info.workspace_external_id, assignments))
    return owners


def workspace_owners(
    resolver: InventoryResolver,
    provider: str,
    workspace_id: str,
    assignments: Assignments | None = None,
) -> list[Owner]:
    if workspace_id == KEY_DEFAULT_WORKSPACE:
        return []
    label = resolver.workspace_label(provider, workspace_id)
    owners: list[Owner] = []
    assigned = assigned_owner(assignments or {}, "workspace", workspace_id, label)
    if assigned is not None:
        owners.append(assigned)
    owners.extend(
        Owner(email=email, role=WORKSPACE_ADMIN, source=label)
        for email in resolver.workspace_admins(provider, workspace_id)
        if _known(email)
    )
    return owners


def owners_gap(
    resolver: InventoryResolver, row: SpendAnomaly, assignments: Assignments | None = None
) -> str | None:
    """Why the provider inventory names nobody for the anomaly, or None when it names someone
    or a contact was assigned in Costura.

    The sentence names the missing fact (a key absent from the listing, a creator id with no
    member record, a workspace without administrators) so the reader knows what to look up
    at the provider instead of writing to the fallback contact."""
    provider = row.provider
    assignments = assignments or {}
    if row.series_kind == "api_key":
        if key_owners(resolver, provider, row.series_id, assignments):
            return None
        return _key_gap(resolver, provider, row.series_id)
    if row.series_kind == "account":
        if account_owners(resolver, provider, row.series_id):
            return None
        return (
            f"The login id `{row.series_id}` is not in the provider's member list, so it maps "
            "to no e-mail."
        )
    for cause in row.root_causes:
        kind, cause_id = str(cause["kind"]), str(cause["id"])
        if kind == "api_key" and key_owners(resolver, provider, cause_id, assignments):
            return None
        if kind == "account" and account_owners(resolver, provider, cause_id):
            return None
    return "None of the top contributors is tied to a person in the provider inventory."


def _key_gap(resolver: InventoryResolver, provider: str, key_id: str) -> str:
    info = resolver.api_key(provider, key_id)
    if info is None:
        return (
            f"The provider's key listing does not include this key; the usage report names "
            f"it only as `{key_id}`. Nobody is recorded as its creator."
        )
    parts: list[str] = []
    if info.created_by_external_id is None:
        parts.append("The provider records no creator for this key")
    else:
        parts.append(
            f"The key's creator id `{info.created_by_external_id}` is not in the provider's "
            "member list, so it maps to no e-mail"
        )
    if info.workspace_external_id is None:
        parts.append("the key belongs to no workspace")
    else:
        workspace = resolver.workspace_label(provider, info.workspace_external_id)
        parts.append(f"the provider lists no administrators for {workspace}")
    return "; ".join(parts) + "."


def _known(email: str) -> bool:
    return bool(email) and NOT_IN_INVENTORY not in email


def _dedupe(owners: list[Owner]) -> list[Owner]:
    seen: set[str] = set()
    unique: list[Owner] = []
    for owner in owners:
        key = owner.email.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(owner)
    return unique
