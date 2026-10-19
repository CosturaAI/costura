"""Team and team mapping shapes."""

from datetime import datetime

from pydantic import BaseModel

from costura.models.team import TeamMemberKind


class TeamIn(BaseModel):
    name: str


class TeamMemberOut(BaseModel):
    kind: TeamMemberKind
    # `all` for a person; the key's or the workspace's provider otherwise.
    provider: str
    # The e-mail, the provider key id or the provider workspace id.
    external_id: str
    label: str
    updated_at: datetime


class TeamOut(BaseModel):
    slug: str
    name: str
    members: list[TeamMemberOut]


class TeamsOut(BaseModel):
    teams: list[TeamOut]
