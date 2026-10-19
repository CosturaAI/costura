"""Teams: cost centers that group people, API keys and workspaces across providers.

A line counts under the team of its API key, else of its person (the e-mail the `person`
dimension folds it under), else of its workspace; spend none of them maps is "(no team)".
An entity belongs to one team at most.
"""

from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base
from costura.models.checks import one_of

TeamMemberKind = Literal["person", "api_key", "workspace"]
TEAM_MEMBER_KINDS: tuple[TeamMemberKind, ...] = get_args(TeamMemberKind)
# The provider a person mapping is stored under: an e-mail crosses every provider.
TEAM_PERSON_PROVIDER = "all"


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("organization_id", "slug"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "kind", "provider", "external_id"),
        one_of("kind", TEAM_MEMBER_KINDS),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[TeamMemberKind] = mapped_column(Text, nullable=False)
    # `all` for a person; the provider of the key or the workspace otherwise.
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    # The lowercased e-mail, the provider key id or the provider workspace id.
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
