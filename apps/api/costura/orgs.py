"""Look up, create, reset organizations (tenants) and manage their members."""

from dataclasses import dataclass

from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from costura import scheduler_lock
from costura.errors import DomainError, InvalidInput
from costura.models import (
    AnomalySettings,
    CreditPrice,
    OrganizationMember,
    OwnerAssignment,
    PersonalKeyAssignment,
    ProviderAccount,
    ProviderApiKey,
    ProviderCredential,
    ProviderInventoryEvent,
    ProviderInvoice,
    ProviderLimit,
    ProviderModelSeen,
    ProviderReportPage,
    ProviderSyncRun,
    ProviderUser,
    ProviderWorkspace,
    ProviderWorkspaceMember,
    SchedulerRun,
    SignalEvent,
    SignalRead,
    SignalSnooze,
    SpendActivityLine,
    SpendAllocatedLine,
    SpendAnomaly,
    SpendBudget,
    SpendBudgetAlert,
    SpendCostLine,
    SpendProjection,
    SpendUsageLine,
    Team,
    TeamMember,
    User,
    WebhookDelivery,
    WebhookDestination,
)
from costura.models.invitation import OrganizationInvitation
from costura.models.organization import DEMO_ORG_SLUG, SLUG_PATTERN, Organization
from costura.models.user import ROLES

# Every table with an `organization_id` that a reset deletes, children before the tables they
# reference. `tests/test_orgs.py` checks the list against the metadata. Memberships,
# invitations, anomaly settings, the webhook destination and the audit trail stay: a reset
# keeps the people who can see the organization, where its signals go and what was done.
RESET_TABLES = (
    WebhookDelivery,
    TeamMember,
    Team,
    SignalEvent,
    SignalSnooze,
    SignalRead,
    SpendBudgetAlert,
    SpendBudget,
    SpendAnomaly,
    OwnerAssignment,
    PersonalKeyAssignment,
    SpendProjection,
    CreditPrice,
    ProviderInvoice,
    ProviderCredential,
    SpendAllocatedLine,
    SpendActivityLine,
    SpendCostLine,
    SpendUsageLine,
    ProviderInventoryEvent,
    ProviderLimit,
    ProviderApiKey,
    ProviderWorkspaceMember,
    ProviderUser,
    ProviderWorkspace,
    ProviderReportPage,
    ProviderModelSeen,
    SchedulerRun,
    ProviderSyncRun,
    ProviderAccount,
)


class UnknownOrganization(LookupError, DomainError):
    status = 404
    code = "unknown_organization"

    def __init__(self, slug: str) -> None:
        super().__init__(f"unknown organization {slug!r}")
        self.slug = slug


class InvalidSlug(ValueError, DomainError):
    status = 422
    code = "invalid_slug"

    def __init__(self, slug: str) -> None:
        super().__init__(
            f"invalid organization slug {slug!r}: lowercase letters, digits and hyphens, "
            "2 to 63 characters, starting with a letter or digit"
        )


class DuplicateSlug(ValueError, DomainError):
    status = 409
    code = "duplicate_slug"

    def __init__(self, slug: str) -> None:
        super().__init__(f"organization {slug!r} already exists")


class ReservedSlug(ValueError, DomainError):
    status = 409
    code = "reserved_slug"

    def __init__(self, slug: str) -> None:
        super().__init__(
            f"organization slug {slug!r} is reserved for this deployment; choose another address"
        )


RESERVED_PREFIXES = ("demo-staging-", "demo-retired-")


def is_sample_slug(slug: str) -> bool:
    """The sample organization and the staging and retired copies its refresh creates."""
    return slug == DEMO_ORG_SLUG or slug.startswith(RESERVED_PREFIXES)


def ensure_open_slug(slug: str, operator_slug: str) -> None:
    """Refuse the slugs a web caller may not claim: the one the environment provider keys
    bind to (`COSTURA_ORG`) and the sample organization's."""
    if slug == operator_slug or is_sample_slug(slug):
        raise ReservedSlug(slug)


class OrganizationBusy(RuntimeError, DomainError):
    """A reset cannot run while the organization has queued or running sync work."""

    status = 409
    code = "organization_busy"


class InvalidRole(ValueError, DomainError):
    status = 422
    code = "invalid_role"

    def __init__(self, role: str) -> None:
        super().__init__(f"invalid role {role!r}: one of {', '.join(ROLES)}")


def get_org(session: Session, slug: str) -> Organization:
    org = session.scalar(select(Organization).where(Organization.slug == slug))
    if org is None:
        raise UnknownOrganization(slug)
    return org


def create_org(
    session: Session, slug: str, name: str, *, owner: User | None = None, is_demo: bool = False
) -> Organization:
    """Create the organization; `owner`, when given, becomes its first `owner` member."""
    if not SLUG_PATTERN.match(slug):
        raise InvalidSlug(slug)
    if session.scalar(select(Organization.id).where(Organization.slug == slug)) is not None:
        raise DuplicateSlug(slug)
    org = Organization(slug=slug, name=name, is_demo=is_demo)
    session.add(org)
    session.flush()
    if owner is not None:
        session.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"))
    session.flush()
    return org


MAX_NAME_LENGTH = 120


class InvalidName(ValueError, DomainError):
    status = 422
    code = "invalid_name"

    def __init__(self) -> None:
        super().__init__(f"name must be 1 to {MAX_NAME_LENGTH} characters after trimming")


def clean_name(name: str) -> str:
    """The display name as stored: trimmed, non-blank, at most `MAX_NAME_LENGTH` characters."""
    cleaned = name.strip()
    if not cleaned or len(cleaned) > MAX_NAME_LENGTH:
        raise InvalidName()
    return cleaned


def rename_org(session: Session, org: Organization, name: str) -> Organization:
    """Change the display name; the slug is the immutable id and has no rename path."""
    org.name = clean_name(name)
    session.flush()
    return org


class OrganizationClaimed(RuntimeError, DomainError):
    status = 409
    code = "organization_claimed"

    def __init__(self, slug: str) -> None:
        super().__init__(f"organization {slug!r} already has members; manage them in the web app")


def claim_first_owner(
    session: Session, slug: str, user: User, *, create: bool = False
) -> OrganizationMember:
    """Make `user` the first owner of an organization that has no members. With `create`,
    a missing organization is created first, which is how the operator opens the one named
    by `COSTURA_ORG`. The organization row is locked so two concurrent claims cannot both
    succeed."""
    org = session.scalar(select(Organization).where(Organization.slug == slug).with_for_update())
    if org is None and create:
        if is_sample_slug(slug):
            raise ReservedSlug(slug)
        try:
            create_org(session, slug, slug)
        except IntegrityError as exc:
            raise DuplicateSlug(slug) from exc
        org = session.scalar(
            select(Organization).where(Organization.slug == slug).with_for_update()
        )
    if org is None:
        raise UnknownOrganization(slug)
    has_members = session.scalar(
        select(OrganizationMember.user_id).where(OrganizationMember.organization_id == org.id)
    )
    if has_members is not None:
        raise OrganizationClaimed(slug)
    row = OrganizationMember(organization_id=org.id, user_id=user.id, role="owner")
    session.add(row)
    session.flush()
    return row


def visible_orgs(session: Session, user_id: int) -> list[tuple[Organization, str | None]]:
    """The organizations `user_id` belongs to, with the role, ordered by slug. The demo
    organization is public and not tied to anyone, so it is listed only through a membership
    (which the seed never creates)."""
    rows = session.execute(
        select(Organization, OrganizationMember.role)
        .join(
            OrganizationMember,
            (OrganizationMember.organization_id == Organization.id)
            & (OrganizationMember.user_id == user_id),
        )
        .order_by(Organization.slug)
    ).all()
    return [(org, role) for org, role in rows]


def demo_org_slug(session: Session) -> str | None:
    """Slug of the seeded public sample organization, or None before `just api::demo-seed`."""
    return session.scalar(
        select(Organization.slug).where(Organization.is_demo.is_(True)).order_by(Organization.id)
    )


@dataclass(frozen=True)
class ResetResult:
    """Rows deleted per table, in deletion order."""

    deleted: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.deleted.values())


def reset_organization(session: Session, org_id: int) -> ResetResult:
    """Return the organization to the state before its first key: every stored credential,
    every synced, derived and configured row of the organization, and the dismissed
    getting-started card, in one transaction. The row in `organizations` stays; other
    organizations are untouched. Keys provided by the environment are not stored rows and
    remain in effect."""

    bind = session.get_bind()
    with scheduler_lock.lock_connection(bind if isinstance(bind, Engine) else bind.engine) as lock:
        if not scheduler_lock.try_organization_lock(lock, org_id):
            raise OrganizationBusy("organization sync is active; wait for it to finish")
        try:
            scheduler_lock.recover_abandoned_runs(session, organization_id=org_id)
            org = session.scalar(
                select(Organization).where(Organization.id == org_id).with_for_update()
            )
            active = session.scalar(
                select(SchedulerRun)
                .where(
                    SchedulerRun.organization_id == org_id,
                    SchedulerRun.status.in_(scheduler_lock.ACTIVE_RUN_STATUSES),
                )
                .order_by(SchedulerRun.id)
                .limit(1)
            )
            if active is not None:
                raise OrganizationBusy(
                    f"organization sync is {active.status} (scheduler run {active.id}); "
                    "wait for it to finish"
                )
            deleted: dict[str, int] = {}
            for model in RESET_TABLES:
                result = session.execute(delete(model).where(model.organization_id == org_id))
                deleted[model.__tablename__] = result.rowcount  # ty: ignore[unresolved-attribute]
            if org is not None:
                org.onboarding_dismissed_at = None
            session.commit()
            session.expire_all()
            return ResetResult(deleted=deleted)
        finally:
            scheduler_lock.unlock_organization(lock, org_id)


DELETE_TABLES = (
    *RESET_TABLES,
    OrganizationInvitation,
    OrganizationMember,
    AnomalySettings,
    WebhookDestination,
)


def delete_organization(session: Session, org: Organization, *, confirm_slug: str) -> None:
    """Delete the organization and every row that belongs to it.

    The caller must pass the slug again. A running or queued sync raises `OrganizationBusy`.
    The organization row goes last, after memberships, invitations, anomaly settings and the
    webhook destination. Audit events stay.
    """
    if confirm_slug != org.slug:
        raise InvalidInput("confirmation slug does not match")
    bind = session.get_bind()
    with scheduler_lock.lock_connection(bind if isinstance(bind, Engine) else bind.engine) as lock:
        if not scheduler_lock.try_organization_lock(lock, org.id):
            raise OrganizationBusy("organization sync is active; wait for it to finish")
        try:
            scheduler_lock.recover_abandoned_runs(session, organization_id=org.id)
            held = session.scalar(
                select(Organization).where(Organization.id == org.id).with_for_update()
            )
            active = session.scalar(
                select(SchedulerRun)
                .where(
                    SchedulerRun.organization_id == org.id,
                    SchedulerRun.status.in_(scheduler_lock.ACTIVE_RUN_STATUSES),
                )
                .limit(1)
            )
            if held is None:
                raise UnknownOrganization(org.slug)
            if active is not None:
                raise OrganizationBusy(
                    f"organization sync is {active.status} (scheduler run {active.id}); "
                    "wait for it to finish"
                )
            for model in DELETE_TABLES:
                session.execute(delete(model).where(model.organization_id == org.id))
            session.delete(held)
            session.commit()
        finally:
            scheduler_lock.unlock_organization(lock, org.id)
