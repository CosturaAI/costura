"""Cost allocated from workspace-level cost buckets to the API keys and accounts that used them.

Derived data: `spend.allocate.run_allocation` replaces the rows of a window on every run.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base

ALLOCATION_METHOD_TOKEN_SHARE = "token_share"
# The provider already priced the usage per key; the allocated amount is copied, not split.
ALLOCATION_METHOD_PROVIDER_ATTRIBUTED = "provider_attributed"
# The cost report itself names the key (OpenAI `api_key_id`); the bucket goes to that key whole.
ALLOCATION_METHOD_KEY_ATTRIBUTED = "key_attributed"
ALLOCATION_ENDPOINT = "allocation"

# One cost bucket (the cost report's pricing grain) split across the principals that used it.
ALLOCATED_LINE_KEY = (
    "organization_id",
    "provider",
    "provider_account_id",
    "period_start",
    "workspace_id",
    "description",
    "cost_type",
    "model",
    "token_type",
    "service_tier",
    "context_window",
    "inference_geo",
    "api_key_id",
    "account_id",
)


class SpendAllocatedLine(Base):
    __tablename__ = "spend_allocated_lines"
    __table_args__ = (
        UniqueConstraint(
            *ALLOCATED_LINE_KEY,
            name="uq_spend_allocated_lines_key",
            postgresql_nulls_not_distinct=True,
        ),
        UniqueConstraint("organization_id", "id", name="uq_spend_allocated_lines_org_id"),
        Index(
            "ix_spend_allocated_lines_org_provider_period_start",
            "organization_id",
            "provider",
            "period_start",
        ),
        Index("ix_spend_allocated_lines_allocation_run_id", "allocation_run_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("provider_accounts.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    api_key_id: Mapped[str | None] = mapped_column(Text)
    account_id: Mapped[str | None] = mapped_column(Text)
    cost_type: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    token_type: Mapped[str | None] = mapped_column(Text)
    service_tier: Mapped[str | None] = mapped_column(Text)
    context_window: Mapped[str | None] = mapped_column(Text)
    inference_geo: Mapped[str | None] = mapped_column(Text)
    # Share basis of this row and of the whole bucket (tokens, or web search requests).
    tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bucket_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bucket_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    # Set only on rows that hold cost no usage line could absorb (api_key_id and account_id null).
    unallocated_reason: Mapped[str | None] = mapped_column(Text)
    allocation_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("provider_sync_runs.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
