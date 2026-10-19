from fastapi import APIRouter, Response

from costura import audit
from costura.api import schemas
from costura.api.deps import CurrentUserDep, OrgDep, OwnedOrgDep, SessionDep
from costura.api.guard import VerifiedWriteDep
from costura.models import TeamMember
from costura.models.team import TeamMemberKind
from costura.spend import teams
from costura.spend.inventory import InventoryResolver
from costura.spend.scope import ALL

router = APIRouter()


def _member_out(resolver: InventoryResolver, row: TeamMember) -> schemas.TeamMemberOut:
    if row.kind == "api_key":
        label = resolver.api_key_label(row.provider, row.external_id)
    elif row.kind == "workspace":
        label = resolver.workspace_label(row.provider, row.external_id)
    else:
        label = row.external_id
    return schemas.TeamMemberOut(
        kind=row.kind,
        provider=row.provider,
        external_id=row.external_id,
        label=label,
        updated_at=row.updated_at,
    )


def _team_out(resolver: InventoryResolver, view: teams.TeamView) -> schemas.TeamOut:
    return schemas.TeamOut(
        slug=view.team.slug,
        name=view.team.name,
        members=[_member_out(resolver, m) for m in view.members],
    )


def _teams_out(session: SessionDep, org_id: int) -> schemas.TeamsOut:
    resolver = InventoryResolver(session, org_id, ALL)
    return schemas.TeamsOut(
        teams=[_team_out(resolver, v) for v in teams.list_teams(session, org_id)]
    )


@router.get("/orgs/{org}/teams", response_model=schemas.TeamsOut)
def teams_route(session: SessionDep, org: OrgDep) -> schemas.TeamsOut:
    """Every team with the people, API keys and workspaces mapped to it. A line counts under
    its key's team, else its person's, else its workspace's; `by=team` groups spend so."""
    return _teams_out(session, org.id)


@router.put("/orgs/{org}/teams/{slug}", response_model=schemas.TeamsOut)
def set_team_route(
    session: SessionDep,
    org: OwnedOrgDep,
    slug: str,
    body: schemas.TeamIn,
    _guard: VerifiedWriteDep,
) -> schemas.TeamsOut:
    """Create the team or rename it. 422 on a slug other than lowercase letters, digits and
    hyphens, or an empty name."""
    teams.set_team(session, org.id, slug, body.name)
    audit.record("team_saved", session=session, org_id=org.id, target=slug, name=body.name)
    return _teams_out(session, org.id)


@router.delete("/orgs/{org}/teams/{slug}", status_code=204)
def delete_team_route(
    session: SessionDep, org: OwnedOrgDep, slug: str, _guard: VerifiedWriteDep
) -> Response:
    """Remove the team with its mappings and its budgets; its spend reads "(no team)"."""
    teams.delete_team(session, org.id, slug)
    audit.record("team_deleted", session=session, org_id=org.id, target=slug)
    return Response(status_code=204)


@router.put(
    "/orgs/{org}/teams/{slug}/members/{kind}/{provider}/{external_id}",
    response_model=schemas.TeamsOut,
)
def set_team_member_route(
    session: SessionDep,
    org: OwnedOrgDep,
    slug: str,
    kind: TeamMemberKind,
    provider: str,
    external_id: str,
    user: CurrentUserDep,
    _guard: VerifiedWriteDep,
) -> schemas.TeamsOut:
    """Map a person (provider `all`, the e-mail), an API key or a workspace (its provider and
    id) to the team; an entity in another team moves. 404 when the team or the entity is not
    in the organization."""
    teams.set_member(session, org.id, slug, kind, provider, external_id, user_id=user.id)
    audit.record(
        "team_member_set",
        session=session,
        org_id=org.id,
        target=slug,
        kind=kind,
        provider=provider,
        external_id=external_id,
    )
    return _teams_out(session, org.id)


@router.delete("/orgs/{org}/teams/{slug}/members/{kind}/{provider}/{external_id}", status_code=204)
def delete_team_member_route(
    session: SessionDep,
    org: OwnedOrgDep,
    slug: str,
    kind: TeamMemberKind,
    provider: str,
    external_id: str,
    _guard: VerifiedWriteDep,
) -> Response:
    teams.delete_member(session, org.id, slug, kind, provider, external_id)
    audit.record(
        "team_member_removed",
        session=session,
        org_id=org.id,
        target=slug,
        kind=kind,
        provider=provider,
        external_id=external_id,
    )
    return Response(status_code=204)
