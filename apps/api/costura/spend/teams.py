"""Create teams and map people, API keys and workspaces to them.

`InventoryResolver.team_of` reads the mappings when the `team` dimension groups a line. A
mapping names an entity of the inventory; moving an entity to another team replaces its row,
so an entity belongs to one team at most. Deleting a team deletes its mappings and its
budgets.
"""

import re
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from costura.errors import InvalidInput, NotFound
from costura.models import (
    ProviderApiKey,
    SpendBudget,
    SpendBudgetAlert,
    Team,
    TeamMember,
)
from costura.models.team import TEAM_MEMBER_KINDS, TEAM_PERSON_PROVIDER, TeamMemberKind
from costura.providers.registry import provider_names
from costura.spend.assignments import person_exists, workspace_exists

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MAX_NAME = 80


@dataclass
class TeamView:
    team: Team
    members: list[TeamMember] = field(default_factory=list)


def list_teams(session: Session, org_id: int) -> list[TeamView]:
    views = {
        t.id: TeamView(team=t)
        for t in session.scalars(
            select(Team).where(Team.organization_id == org_id).order_by(Team.name, Team.slug)
        )
    }
    for member in session.scalars(
        select(TeamMember)
        .where(TeamMember.organization_id == org_id)
        .order_by(TeamMember.kind, TeamMember.provider, TeamMember.external_id)
    ):
        if member.team_id in views:
            views[member.team_id].members.append(member)
    return list(views.values())


def get_team(session: Session, org_id: int, slug: str) -> Team:
    team = session.scalar(select(Team).where(Team.organization_id == org_id, Team.slug == slug))
    if team is None:
        raise NotFound("team not found")
    return team


def set_team(session: Session, org_id: int, slug: str, name: str) -> Team:
    """Create the team or rename it. 422 on a malformed slug or an empty name."""
    if not SLUG.match(slug):
        raise InvalidInput("a team slug is lowercase letters, digits and hyphens")
    name = name.strip()
    if not name or len(name) > MAX_NAME:
        raise InvalidInput(f"a team name has 1 to {MAX_NAME} characters")
    team = session.scalar(select(Team).where(Team.organization_id == org_id, Team.slug == slug))
    if team is None:
        team = Team(organization_id=org_id, slug=slug, name=name)
        session.add(team)
    else:
        team.name = name
    session.flush()
    return team


def delete_team(session: Session, org_id: int, slug: str) -> None:
    team = get_team(session, org_id, slug)
    budgets = select(SpendBudget.id).where(
        SpendBudget.organization_id == org_id,
        SpendBudget.scope_kind == "team",
        SpendBudget.scope_id == slug,
    )
    session.execute(delete(SpendBudgetAlert).where(SpendBudgetAlert.budget_id.in_(budgets)))
    session.execute(
        delete(SpendBudget).where(
            SpendBudget.organization_id == org_id,
            SpendBudget.scope_kind == "team",
            SpendBudget.scope_id == slug,
        )
    )
    session.execute(delete(TeamMember).where(TeamMember.team_id == team.id))
    session.delete(team)
    session.flush()


def _member_identity(
    session: Session, org_id: int, kind: str, provider: str, external_id: str
) -> tuple[TeamMemberKind, str, str]:
    if kind not in TEAM_MEMBER_KINDS:
        raise InvalidInput(f"kind must be one of {', '.join(TEAM_MEMBER_KINDS)}")
    if kind == "person":
        email = external_id.strip().lower()
        if provider != TEAM_PERSON_PROVIDER:
            raise InvalidInput("a person is mapped under provider all")
        if not person_exists(session, org_id, email):
            raise NotFound("person not found")
        return "person", provider, email
    if provider not in provider_names():
        raise InvalidInput("a key or a workspace is mapped under its own provider")
    if kind == "workspace":
        if not workspace_exists(session, org_id, provider, external_id):
            raise NotFound("workspace not found")
        return "workspace", provider, external_id
    found = session.scalar(
        select(func.count())
        .select_from(ProviderApiKey)
        .where(
            ProviderApiKey.organization_id == org_id,
            ProviderApiKey.provider == provider,
            ProviderApiKey.external_id == external_id,
        )
    )
    if not found:
        raise NotFound("API key not found")
    return "api_key", provider, external_id


def set_member(
    session: Session,
    org_id: int,
    slug: str,
    kind: str,
    provider: str,
    external_id: str,
    *,
    user_id: int | None,
) -> TeamMember:
    """Map an entity to the team, moving it from another team when it had one."""
    team = get_team(session, org_id, slug)
    member_kind, member_provider, member_id = _member_identity(
        session, org_id, kind, provider, external_id
    )
    session.execute(
        pg_insert(TeamMember)
        .values(
            organization_id=org_id,
            team_id=team.id,
            kind=member_kind,
            provider=member_provider,
            external_id=member_id,
            assigned_by=user_id,
        )
        .on_conflict_do_update(
            index_elements=["organization_id", "kind", "provider", "external_id"],
            set_={"team_id": team.id, "assigned_by": user_id, "updated_at": func.now()},
        )
    )
    member = session.scalar(
        select(TeamMember).where(
            TeamMember.organization_id == org_id,
            TeamMember.kind == member_kind,
            TeamMember.provider == member_provider,
            TeamMember.external_id == member_id,
        )
    )
    assert member is not None
    session.refresh(member)
    return member


def delete_member(
    session: Session, org_id: int, slug: str, kind: str, provider: str, external_id: str
) -> None:
    team = get_team(session, org_id, slug)
    if kind == "person":
        external_id = external_id.strip().lower()
    member = session.scalar(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.kind == kind,
            TeamMember.provider == provider,
            TeamMember.external_id == external_id,
        )
    )
    if member is None:
        raise NotFound("not in this team")
    session.delete(member)
    session.flush()
