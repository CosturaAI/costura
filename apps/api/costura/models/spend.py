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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base

# Natural keys include nullable dimensions (default workspace, playground usage), so the
# unique constraints are declared NULLS NOT DISTINCT (PostgreSQL 15+).
COST_LINE_KEY = (
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
)
USAGE_LINE_KEY = (
    "organization_id",
    "provider",
    "provider_account_id",
    "period_start",
    "api_key_id",
    "account_id",
    "workspace_id",
    "model",
    "service_tier",
    "context_window",
    "inference_geo",
    "product",
)
ACTIVITY_LINE_KEY = (
    "organization_id",
    "provider",
    "provider_account_id",
    "period_start",
    "family",
    "workspace_id",
    "api_key_id",
    "account_id",
    "model",
    "detail",
)


class SpendCostLine(Base):
    """Provider-billed amount for one day and one cost dimension tuple."""

    __tablename__ = "spend_cost_lines"
    __table_args__ = (
        UniqueConstraint(
            *COST_LINE_KEY, name="uq_spend_cost_lines_key", postgresql_nulls_not_distinct=True
        ),
        Index(
            "ix_spend_cost_lines_org_provider_period_start",
            "organization_id",
            "provider",
            "period_start",
        ),
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
    description: Mapped[str] = mapped_column(Text, nullable=False)
    cost_type: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    token_type: Mapped[str | None] = mapped_column(Text)
    service_tier: Mapped[str | None] = mapped_column(Text)
    context_window: Mapped[str | None] = mapped_column(Text)
    inference_geo: Mapped[str | None] = mapped_column(Text)
    # Set when the provider reports the bucket under one API key (OpenAI); NULL otherwise.
    api_key_id: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    list_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    raw_amount_minor: Mapped[str] = mapped_column(Text, nullable=False)
    sync_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("provider_sync_runs.id"), nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SpendUsageLine(Base):
    """Token usage for one day, credential or account, workspace, model, tier, context window
    and inference geo: the grain the cost report is priced at, plus who made the request."""

    __tablename__ = "spend_usage_lines"
    __table_args__ = (
        UniqueConstraint(
            *USAGE_LINE_KEY, name="uq_spend_usage_lines_key", postgresql_nulls_not_distinct=True
        ),
        Index(
            "ix_spend_usage_lines_org_provider_period_start",
            "organization_id",
            "provider",
            "period_start",
        ),
        Index(
            "ix_spend_usage_lines_org_provider_key_period",
            "organization_id",
            "provider",
            "api_key_id",
            "period_start",
        ),
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
    api_key_id: Mapped[str | None] = mapped_column(Text)
    account_id: Mapped[str | None] = mapped_column(Text)
    workspace_id: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    service_tier: Mapped[str] = mapped_column(Text, nullable=False)
    context_window: Mapped[str | None] = mapped_column(Text)
    inference_geo: Mapped[str | None] = mapped_column(Text)
    uncached_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cache_creation_5m_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cache_creation_1h_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    web_search_requests: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Counters and provider-attributed cost that only some providers report.
    reasoning_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    request_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    currency: Mapped[str | None] = mapped_column(Text)
    # Inference cost routed through the line's provider to another provider's key (BYOK);
    # billed by that other provider, so never part of `amount` or any total.
    byok_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    # Provider-reported list-price amount and product surface. These are distinct from the
    # configured model-rate catalog and canonical model dimensions.
    list_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    product: Mapped[str | None] = mapped_column(Text)
    sync_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("provider_sync_runs.id"), nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SpendActivityLine(Base):
    """Non-completions provider activity at the finest supported billing grain."""

    __tablename__ = "spend_activity_lines"
    __table_args__ = (
        UniqueConstraint(
            *ACTIVITY_LINE_KEY,
            name="uq_spend_activity_lines_key",
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_spend_activity_lines_org_provider_period_start",
            "organization_id",
            "provider",
            "period_start",
        ),
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
    family: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    request_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(Text)
    api_key_id: Mapped[str | None] = mapped_column(Text)
    account_id: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    sync_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("provider_sync_runs.id"), nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
