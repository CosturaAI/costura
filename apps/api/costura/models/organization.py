"""The tenant. Every provider-scoped row carries `organization_id`; the migration that
introduced it created the `default` organization and assigned existing rows to it.
"""

import re
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base

DEMO_ORG_SLUG = "demo"
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Set once the user dismisses the getting-started card; null shows it.
    onboarding_dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Sample organization: readable by every signed-in user, refused every write through the API.
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # The sample dataset an organization holds (`costura.demo`): set on the public `demo` row
    # and on the private staging row a refresh builds before the swap; null everywhere else.
    demo_dataset_version: Mapped[int | None] = mapped_column(Integer)
    demo_generated_through: Mapped[date | None] = mapped_column(Date)
    demo_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
