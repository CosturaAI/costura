"""Who belongs to an organization and with which role: the one read the spend rules make of
tenancy, so a visibility check in `spend` does not import the organization service."""

from sqlalchemy import Case, case, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from costura.models.user import ROLES, OrganizationMember, User


def membership(session: Session, org_id: int, user_id: int) -> OrganizationMember | None:
    return session.get(OrganizationMember, (org_id, user_id))


def role_rank(column: InstrumentedAttribute[str]) -> Case[int]:
    """Sort key that follows the permission ladder; `role` alphabetically would read
    member, owner, viewer."""
    return case({role: i for i, role in enumerate(ROLES)}, value=column, else_=len(ROLES))


def list_members(session: Session, org_id: int) -> list[tuple[User, OrganizationMember]]:
    """Members of one organization with their role, owners first, then by e-mail."""
    rows = session.execute(
        select(User, OrganizationMember)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(OrganizationMember.organization_id == org_id)
        .order_by(role_rank(OrganizationMember.role), User.email)
    ).all()
    return [(user, member) for user, member in rows]
