"""Membership setup the tests share."""

from sqlalchemy.orm import Session

from costura.models import Organization, OrganizationMember, User
from costura.spend.membership import membership


def add_member(
    session: Session, org: Organization, user: User, role: str = "member"
) -> OrganizationMember:
    """Add `user` to `org`, or change the role of an existing membership."""
    row = membership(session, org.id, user.id)
    if row is None:
        row = OrganizationMember(organization_id=org.id, user_id=user.id, role=role)
        session.add(row)
    else:
        row.role = role
    session.flush()
    return row
