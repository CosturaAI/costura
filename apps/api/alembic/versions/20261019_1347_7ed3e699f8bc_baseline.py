"""Baseline schema.

Creates every table. A new database starts empty; the first signed-in user creates an
organization. Install this revision on an empty database. There is no earlier revision to
upgrade from.

Revision ID: 7ed3e699f8bc
Revises:
Create Date: 2026-10-19 13:47:12.567391

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7ed3e699f8bc"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_email", sa.Text(), nullable=True),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_org_created",
        "audit_events",
        ["organization_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "oidc_authorizations",
        sa.Column("state_hash", sa.Text(), nullable=False),
        sa.Column("nonce_hash", sa.Text(), nullable=False),
        sa.Column("code_verifier_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("state_hash", name=op.f("pk_oidc_authorizations")),
    )
    op.create_index(
        op.f("ix_oidc_authorizations_expires_at"),
        "oidc_authorizations",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "organizations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("onboarding_dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_demo", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("demo_dataset_version", sa.Integer(), nullable=True),
        sa.Column("demo_generated_through", sa.Date(), nullable=True),
        sa.Column("demo_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_sign_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "worker_heartbeats",
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "role IN ('worker', 'scheduler')", name=op.f("ck_worker_heartbeats_role")
        ),
        sa.PrimaryKeyConstraint("owner", name=op.f("pk_worker_heartbeats")),
    )
    op.create_table(
        "anomaly_settings",
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("sensitivity", sa.Text(), server_default="normal", nullable=False),
        sa.Column("detect_drops", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("detect_new_principals", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("retention_days", sa.Integer(), server_default="90", nullable=False),
        sa.Column("idle_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column("new_key_days", sa.Integer(), server_default="7", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sensitivity IN ('low', 'normal', 'high')", name=op.f("ck_anomaly_settings_sensitivity")
        ),
        sa.CheckConstraint(
            "idle_days BETWEEN 7 AND 365", name=op.f("ck_anomaly_settings_idle_days")
        ),
        sa.CheckConstraint(
            "new_key_days BETWEEN 1 AND 90", name=op.f("ck_anomaly_settings_new_key_days")
        ),
        sa.CheckConstraint(
            "retention_days BETWEEN 30 AND 365", name=op.f("ck_anomaly_settings_retention_days")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_anomaly_settings_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_anomaly_settings")),
    )
    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("invited_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('owner', 'member', 'viewer')", name=op.f("ck_organization_invitations_role")
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name=op.f("fk_organization_invitations_invited_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_invitations_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_organization_invitations_token_hash")),
    )
    op.create_index(
        "uq_organization_invitations_pending",
        "organization_invitations",
        ["organization_id", "email"],
        unique=True,
        postgresql_where="accepted_at IS NULL AND revoked_at IS NULL",
    )
    op.create_table(
        "organization_members",
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("anomaly_alerts_since", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('owner', 'member', 'viewer')", name=op.f("ck_organization_members_role")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_members_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_organization_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", "user_id", name=op.f("pk_organization_members")),
    )
    op.create_table(
        "personal_key_assignments",
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("api_key_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("assigned_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"],
            ["users.id"],
            name=op.f("fk_personal_key_assignments_assigned_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_personal_key_assignments_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "provider", "api_key_id", name=op.f("pk_personal_key_assignments")
        ),
    )
    op.create_table(
        "provider_accounts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "settings_effective_from",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            """
            provider <> 'cursor' OR (
              jsonb_typeof(settings) = 'object'
              AND (
                NOT settings ? 'seat_price_usd'
                OR (
                  jsonb_typeof(settings->'seat_price_usd') = 'number'
                  AND (settings->>'seat_price_usd')::numeric >= 0
                )
              )
              AND (
                NOT settings ? 'include_included_in_business'
                OR jsonb_typeof(settings->'include_included_in_business') = 'boolean'
              )
            )
            """,
            name=op.f("ck_provider_accounts_cursor_settings"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_accounts_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_accounts")),
        sa.UniqueConstraint(
            "organization_id", "provider", "label", name="uq_provider_accounts_label"
        ),
    )
    op.create_index(
        "uq_provider_accounts_external_id",
        "provider_accounts",
        ["organization_id", "provider", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_table(
        "provider_models_seen",
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("first_seen", sa.Date(), nullable=False),
        sa.Column("last_seen", sa.Date(), nullable=False),
        sa.Column(
            "last_amount_30d", sa.Numeric(precision=20, scale=8), server_default="0", nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(model) BETWEEN 1 AND 255",
            name=op.f("ck_provider_models_seen_model_length"),
        ),
        sa.CheckConstraint(
            "char_length(provider) BETWEEN 1 AND 64",
            name=op.f("ck_provider_models_seen_provider_length"),
        ),
        sa.CheckConstraint(
            "first_seen <= last_seen", name=op.f("ck_provider_models_seen_seen_range")
        ),
        sa.CheckConstraint(
            "last_amount_30d >= 0", name=op.f("ck_provider_models_seen_amount_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_models_seen_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "provider", "model", name=op.f("pk_provider_models_seen")
        ),
    )
    op.create_index(
        "ix_provider_models_seen_org_last",
        "provider_models_seen",
        ["organization_id", "last_seen"],
        unique=False,
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("identity_provider", sa.Text(), server_default="dev", nullable=False),
        sa.CheckConstraint(
            "identity_provider IN ('dev', 'google')", name=op.f("ck_sessions_identity_provider")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)
    op.create_table(
        "signal_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("entity_kind", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("dollars_at_risk", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            (
                "kind IN ('anomaly', 'budget', 'sync_stale', 'webhook_failing', "
                "'model_retiring', 'near_limit', 'idle_seat', 'seat_no_limit', 'unit_cost_up', "
                "'no_owner', 'no_limit', 'owner_left', 'idle_active', 'new_key')"
            ),
            name=op.f("ck_signal_events_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_signal_events_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signal_events")),
    )
    op.create_index(
        "ix_signal_events_org_closed_at",
        "signal_events",
        ["organization_id", "closed_at"],
        unique=False,
    )
    op.create_index(
        "ix_signal_events_org_entity",
        "signal_events",
        ["organization_id", "kind", "provider", "entity_kind", "entity_id"],
        unique=False,
    )
    op.create_table(
        "signal_reads",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column(
            "read_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            (
                "kind IN ('budget', 'sync_stale', 'webhook_failing', 'model_retiring', "
                "'near_limit', 'idle_seat', 'seat_no_limit', 'unit_cost_up', 'no_owner', "
                "'no_limit', 'owner_left', 'idle_active', 'new_key')"
            ),
            name=op.f("ck_signal_reads_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_signal_reads_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_signal_reads_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signal_reads")),
        sa.UniqueConstraint(
            "user_id", "organization_id", "kind", "provider", "reference", name="uq_signal_reads"
        ),
    )
    op.create_index(
        "ix_signal_reads_organization_id", "signal_reads", ["organization_id"], unique=False
    )
    op.create_table(
        "signal_snoozes",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("until", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            (
                "kind IN ('no_owner', 'no_limit', 'owner_left', 'idle_active', 'new_key', "
                "'idle_seat', 'seat_no_limit')"
            ),
            name=op.f("ck_signal_snoozes_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_signal_snoozes_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_signal_snoozes_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signal_snoozes")),
        sa.UniqueConstraint(
            "organization_id", "kind", "provider", "key_id", name="uq_signal_snoozes"
        ),
    )
    op.create_table(
        "spend_budgets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("scope_kind", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("thresholds", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("period", sa.Text(), server_default="month", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "period IN ('month', 'week', 'day')", name=op.f("ck_spend_budgets_period")
        ),
        sa.CheckConstraint(
            "scope_kind IN ('org', 'workspace', 'person', 'team')",
            name=op.f("ck_spend_budgets_scope_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_spend_budgets_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spend_budgets")),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "scope_kind",
            "scope_id",
            name=op.f("uq_spend_budgets_organization_id"),
        ),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_teams_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
        sa.UniqueConstraint("organization_id", "slug", name=op.f("uq_teams_organization_id")),
    )
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            (
                "kind IN ('anomaly', 'budget', 'sync_stale', 'model_retiring', 'near_limit', "
                "'idle_seat', 'seat_no_limit', 'unit_cost_up', 'no_owner', 'no_limit', "
                "'owner_left', 'idle_active', 'new_key')"
            ),
            name=op.f("ck_webhook_deliveries_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped')",
            name=op.f("ck_webhook_deliveries_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_webhook_deliveries_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
        sa.UniqueConstraint(
            "organization_id", "kind", "provider", "reference", name="uq_webhook_deliveries"
        ),
    )
    op.create_index(
        "ix_webhook_deliveries_org_status_next",
        "webhook_deliveries",
        ["organization_id", "status", "next_attempt_at"],
        unique=False,
    )
    op.create_table(
        "webhook_destinations",
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("url_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("url_host", sa.Text(), nullable=False),
        sa.Column("secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("digest", sa.Text(), server_default="off", nullable=False),
        sa.Column("last_digest_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "digest IN ('off', 'weekly', 'monthly')", name=op.f("ck_webhook_destinations_digest")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_webhook_destinations_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_webhook_destinations")),
    )
    op.create_table(
        "credit_prices",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("price_per_credit", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "price_per_credit > 0", name=op.f("ck_credit_prices_price_per_credit_positive")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_credit_prices_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_credit_prices_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_credit_prices_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_prices")),
        sa.UniqueConstraint(
            "organization_id",
            "provider_account_id",
            "effective_from",
            name="uq_credit_prices_account_effective_from",
        ),
    )
    op.create_table(
        "owner_assignments",
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("assigned_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('api_key', 'workspace')", name=op.f("ck_owner_assignments_kind")
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"],
            ["users.id"],
            name=op.f("fk_owner_assignments_assigned_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_owner_assignments_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_owner_assignments_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "kind",
            "external_id",
            name=op.f("pk_owner_assignments"),
        ),
    )
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("key_digest", sa.Text(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("key_hint", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_provider_credentials_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_credentials_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_credentials")),
        sa.UniqueConstraint("account_id", name=op.f("uq_provider_credentials_account_id")),
        sa.UniqueConstraint(
            "organization_id", "provider", "key_digest", name="uq_provider_credentials_key_digest"
        ),
    )
    op.create_table(
        "provider_invoices",
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("month", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.Text(), server_default="USD", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("entered_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name=op.f("ck_provider_invoices_month")
        ),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_provider_invoices_amount")),
        sa.ForeignKeyConstraint(
            ["entered_by"],
            ["users.id"],
            name=op.f("fk_provider_invoices_entered_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_invoices_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_provider_invoices_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "month",
            name=op.f("pk_provider_invoices"),
        ),
    )
    op.create_table(
        "provider_sync_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=True),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("pages_fetched", sa.Integer(), nullable=False),
        sa.Column("raw_results", sa.Integer(), nullable=False),
        sa.Column("rows_upserted", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name=op.f("ck_provider_sync_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_sync_runs_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_provider_sync_runs_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_sync_runs")),
    )
    op.create_index(
        "ix_provider_sync_runs_org_provider_started",
        "provider_sync_runs",
        ["organization_id", "provider", "started_at"],
        unique=False,
    )
    op.create_table(
        "scheduler_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=True),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')",
            name=op.f("ck_scheduler_runs_status"),
        ),
        sa.CheckConstraint(
            "trigger IN ('scheduler', 'manual', 'api', 'connect')",
            name=op.f("ck_scheduler_runs_trigger"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_scheduler_runs_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_scheduler_runs_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduler_runs")),
    )
    op.create_index(
        "ix_scheduler_runs_claim",
        "scheduler_runs",
        ["priority", "id"],
        unique=False,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index(
        "uq_scheduler_runs_idempotency_key",
        "scheduler_runs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_table(
        "spend_anomalies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("series_kind", sa.Text(), nullable=False),
        sa.Column("series_id", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.Text(), server_default="spike", nullable=False),
        sa.Column("end_day", sa.Date(), nullable=False),
        sa.Column("ongoing", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("duration_days", sa.Integer(), server_default="1", nullable=False),
        sa.Column("actual", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("expected", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("upper_bound", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("lower_bound", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("baseline_method", sa.Text(), server_default="weekday", nullable=False),
        sa.Column("baseline_samples", sa.Integer(), server_default="0", nullable=False),
        sa.Column("impact", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("impact_percent", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("impact_share", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("total_actual", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("total_expected", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("total_impact", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("max_impact", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("deviation", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("severity", sa.Text(), server_default="low", nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), server_default="USD", nullable=False),
        sa.Column("root_causes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("status_changed_by", sa.Text(), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('spike', 'drop', 'new_principal')", name=op.f("ck_spend_anomalies_kind")
        ),
        sa.CheckConstraint(
            "series_kind IN ('org', 'api_key', 'account')",
            name=op.f("ck_spend_anomalies_series_kind"),
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high')", name=op.f("ck_spend_anomalies_severity")
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'ignored')", name=op.f("ck_spend_anomalies_status")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_spend_anomalies_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_spend_anomalies_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spend_anomalies")),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "series_kind",
            "series_id",
            "day",
            name=op.f("uq_spend_anomalies_organization_id"),
        ),
    )
    op.create_index(
        "ix_spend_anomalies_org_provider_day",
        "spend_anomalies",
        ["organization_id", "provider", "day"],
        unique=False,
    )
    op.create_table(
        "spend_budget_alerts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("budget_id", sa.BigInteger(), nullable=False),
        sa.Column("month", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=True),
        sa.Column("spent", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("projected", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('threshold', 'projection')", name=op.f("ck_spend_budget_alerts_kind")
        ),
        sa.ForeignKeyConstraint(
            ["budget_id"],
            ["spend_budgets.id"],
            name=op.f("fk_spend_budget_alerts_budget_id_spend_budgets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_spend_budget_alerts_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spend_budget_alerts")),
        sa.UniqueConstraint(
            "budget_id",
            "month",
            "period_start",
            "kind",
            "threshold",
            name=op.f("uq_spend_budget_alerts_budget_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_spend_budget_alerts_org_provider_month",
        "spend_budget_alerts",
        ["organization_id", "provider", "month"],
        unique=False,
    )
    op.create_table(
        "spend_projections",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("series_kind", sa.Text(), nullable=False),
        sa.Column("series_id", sa.Text(), nullable=False),
        sa.Column("month", sa.Text(), nullable=False),
        sa.Column("as_of_day", sa.Date(), nullable=False),
        sa.Column("mtd", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("projected_total", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("low", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("high", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("days", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "series_kind IN ('org', 'workspace', 'model', 'api_key')",
            name=op.f("ck_spend_projections_series_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_spend_projections_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_spend_projections_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spend_projections")),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "series_kind",
            "series_id",
            "month",
            name=op.f("uq_spend_projections_organization_id"),
        ),
    )
    op.create_table(
        "team_members",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("assigned_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('person', 'api_key', 'workspace')", name=op.f("ck_team_members_kind")
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"],
            ["users.id"],
            name=op.f("fk_team_members_assigned_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_team_members_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_team_members_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_members")),
        sa.UniqueConstraint(
            "organization_id",
            "kind",
            "provider",
            "external_id",
            name=op.f("uq_team_members_organization_id"),
        ),
    )
    op.create_table(
        "anomaly_reads",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("anomaly_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "read_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["anomaly_id"],
            ["spend_anomalies.id"],
            name=op.f("fk_anomaly_reads_anomaly_id_spend_anomalies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_anomaly_reads_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "anomaly_id", name=op.f("pk_anomaly_reads")),
    )
    op.create_index("ix_anomaly_reads_anomaly_id", "anomaly_reads", ["anomaly_id"], unique=False)
    op.create_table(
        "provider_api_keys",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("partial_key_hint", sa.Text(), nullable=True),
        sa.Column("workspace_external_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_external_id", sa.Text(), nullable=True),
        sa.Column("principal_external_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("principal_type", sa.Text(), nullable=True),
        sa.Column("scope_type", sa.Text(), nullable=True),
        sa.Column("limit_reported", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("spend_limit", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("limit_remaining", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("limit_reset", sa.Text(), nullable=True),
        sa.Column("sync_run_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_api_keys_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_provider_api_keys_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["provider_sync_runs.id"],
            name=op.f("fk_provider_api_keys_sync_run_id_provider_sync_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_api_keys")),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "external_id",
            name="uq_provider_api_keys_external_id",
        ),
    )
    op.create_index(
        "ix_provider_api_keys_org_provider_workspace",
        "provider_api_keys",
        ["organization_id", "provider", "workspace_external_id"],
        unique=False,
    )
    op.create_table(
        "provider_inventory_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("entity_kind", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=True),
        sa.Column("sync_run_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_kind IN ('api_key', 'user')",
            name=op.f("ck_provider_inventory_events_entity_kind"),
        ),
        sa.CheckConstraint(
            "event IN ('created', 'status_changed', 'missing', 'returned')",
            name=op.f("ck_provider_inventory_events_event"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_inventory_events_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_provider_inventory_events_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["provider_sync_runs.id"],
            name=op.f("fk_provider_inventory_events_sync_run_id_provider_sync_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_inventory_events")),
    )
    op.create_index(
        "ix_provider_inventory_events_entity",
        "provider_inventory_events",
        ["organization_id", "provider", "entity_kind", "external_id"],
        unique=False,
    )
    op.create_table(
        "provider_limits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("scope_kind", sa.Text(), nullable=False),
        sa.Column("scope_name", sa.Text(), nullable=True),
        sa.Column("product", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("consumed", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("enforcement", sa.Text(), nullable=False),
        sa.Column("sync_run_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "enforcement IN ('hard', 'soft')", name=op.f("ck_provider_limits_enforcement")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_limits_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_provider_limits_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["provider_sync_runs.id"],
            name=op.f("fk_provider_limits_sync_run_id_provider_sync_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_limits")),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "external_id",
            name="uq_provider_limits_external_id",
        ),
    )
    op.create_table(
        "provider_report_pages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("sync_run_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("request_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_report_pages_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["provider_sync_runs.id"],
            name=op.f("fk_provider_report_pages_sync_run_id_provider_sync_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_report_pages")),
        sa.UniqueConstraint(
            "sync_run_id", "page_index", name=op.f("uq_provider_report_pages_sync_run_id")
        ),
    )
    op.create_table(
        "provider_users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kind", sa.Text(), server_default=sa.text("'user'"), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_removal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("limit_reported", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("spend_limit", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("sync_run_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('user', 'service_account')", name=op.f("ck_provider_users_kind")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_users_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_provider_users_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["provider_sync_runs.id"],
            name=op.f("fk_provider_users_sync_run_id_provider_sync_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_users")),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "external_id",
            name="uq_provider_users_external_id",
        ),
    )
    op.create_table(
        "provider_workspace_members",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_external_id", sa.Text(), nullable=False),
        sa.Column("user_external_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("sync_run_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_workspace_members_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_provider_workspace_members_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["provider_sync_runs.id"],
            name=op.f("fk_provider_workspace_members_sync_run_id_provider_sync_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_workspace_members")),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "workspace_external_id",
            "user_external_id",
            name="uq_provider_workspace_members_workspace_user",
        ),
    )
    op.create_table(
        "provider_workspaces",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sync_run_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_workspaces_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_provider_workspaces_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["provider_sync_runs.id"],
            name=op.f("fk_provider_workspaces_sync_run_id_provider_sync_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_workspaces")),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "external_id",
            name="uq_provider_workspaces_external_id",
        ),
    )
    op.create_table(
        "spend_activity_lines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("family", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("request_count", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=True),
        sa.Column("api_key_id", sa.Text(), nullable=True),
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("sync_run_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_spend_activity_lines_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_spend_activity_lines_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["provider_sync_runs.id"],
            name=op.f("fk_spend_activity_lines_sync_run_id_provider_sync_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spend_activity_lines")),
        sa.UniqueConstraint(
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
            name="uq_spend_activity_lines_key",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_spend_activity_lines_org_provider_period_start",
        "spend_activity_lines",
        ["organization_id", "provider", "period_start"],
        unique=False,
    )
    op.create_table(
        "spend_allocated_lines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("api_key_id", sa.Text(), nullable=True),
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("cost_type", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("token_type", sa.Text(), nullable=True),
        sa.Column("service_tier", sa.Text(), nullable=True),
        sa.Column("context_window", sa.Text(), nullable=True),
        sa.Column("inference_geo", sa.Text(), nullable=True),
        sa.Column("tokens", sa.BigInteger(), nullable=False),
        sa.Column("bucket_tokens", sa.BigInteger(), nullable=False),
        sa.Column("bucket_amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("unallocated_reason", sa.Text(), nullable=True),
        sa.Column("allocation_run_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["allocation_run_id"],
            ["provider_sync_runs.id"],
            name=op.f("fk_spend_allocated_lines_allocation_run_id_provider_sync_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_spend_allocated_lines_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_spend_allocated_lines_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spend_allocated_lines")),
        sa.UniqueConstraint("organization_id", "id", name="uq_spend_allocated_lines_org_id"),
        sa.UniqueConstraint(
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
            name="uq_spend_allocated_lines_key",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_spend_allocated_lines_allocation_run_id",
        "spend_allocated_lines",
        ["allocation_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_spend_allocated_lines_org_provider_period_start",
        "spend_allocated_lines",
        ["organization_id", "provider", "period_start"],
        unique=False,
    )
    op.create_table(
        "spend_cost_lines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("cost_type", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("token_type", sa.Text(), nullable=True),
        sa.Column("service_tier", sa.Text(), nullable=True),
        sa.Column("context_window", sa.Text(), nullable=True),
        sa.Column("inference_geo", sa.Text(), nullable=True),
        sa.Column("api_key_id", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("list_amount", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("raw_amount_minor", sa.Text(), nullable=False),
        sa.Column("sync_run_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_spend_cost_lines_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_spend_cost_lines_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["provider_sync_runs.id"],
            name=op.f("fk_spend_cost_lines_sync_run_id_provider_sync_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spend_cost_lines")),
        sa.UniqueConstraint(
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
            name="uq_spend_cost_lines_key",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_spend_cost_lines_org_provider_period_start",
        "spend_cost_lines",
        ["organization_id", "provider", "period_start"],
        unique=False,
    )
    op.create_table(
        "spend_usage_lines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("api_key_id", sa.Text(), nullable=True),
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("workspace_id", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("service_tier", sa.Text(), nullable=False),
        sa.Column("context_window", sa.Text(), nullable=True),
        sa.Column("inference_geo", sa.Text(), nullable=True),
        sa.Column("uncached_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_creation_5m_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_creation_1h_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("web_search_requests", sa.BigInteger(), nullable=False),
        sa.Column("reasoning_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("request_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("byok_amount", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("list_amount", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("product", sa.Text(), nullable=True),
        sa.Column("sync_run_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_spend_usage_lines_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["provider_accounts.id"],
            name=op.f("fk_spend_usage_lines_provider_account_id_provider_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["provider_sync_runs.id"],
            name=op.f("fk_spend_usage_lines_sync_run_id_provider_sync_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spend_usage_lines")),
        sa.UniqueConstraint(
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
            name="uq_spend_usage_lines_key",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_spend_usage_lines_org_provider_key_period",
        "spend_usage_lines",
        ["organization_id", "provider", "api_key_id", "period_start"],
        unique=False,
    )
    op.create_index(
        "ix_spend_usage_lines_org_provider_period_start",
        "spend_usage_lines",
        ["organization_id", "provider", "period_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_spend_usage_lines_org_provider_period_start", table_name="spend_usage_lines")
    op.drop_index("ix_spend_usage_lines_org_provider_key_period", table_name="spend_usage_lines")
    op.drop_table("spend_usage_lines")
    op.drop_index("ix_spend_cost_lines_org_provider_period_start", table_name="spend_cost_lines")
    op.drop_table("spend_cost_lines")
    op.drop_index(
        "ix_spend_allocated_lines_org_provider_period_start", table_name="spend_allocated_lines"
    )
    op.drop_index("ix_spend_allocated_lines_allocation_run_id", table_name="spend_allocated_lines")
    op.drop_table("spend_allocated_lines")
    op.drop_index(
        "ix_spend_activity_lines_org_provider_period_start", table_name="spend_activity_lines"
    )
    op.drop_table("spend_activity_lines")
    op.drop_table("provider_workspaces")
    op.drop_table("provider_workspace_members")
    op.drop_table("provider_users")
    op.drop_table("provider_report_pages")
    op.drop_table("provider_limits")
    op.drop_index("ix_provider_inventory_events_entity", table_name="provider_inventory_events")
    op.drop_table("provider_inventory_events")
    op.drop_index("ix_provider_api_keys_org_provider_workspace", table_name="provider_api_keys")
    op.drop_table("provider_api_keys")
    op.drop_index("ix_anomaly_reads_anomaly_id", table_name="anomaly_reads")
    op.drop_table("anomaly_reads")
    op.drop_table("team_members")
    op.drop_table("spend_projections")
    op.drop_index("ix_spend_budget_alerts_org_provider_month", table_name="spend_budget_alerts")
    op.drop_table("spend_budget_alerts")
    op.drop_index("ix_spend_anomalies_org_provider_day", table_name="spend_anomalies")
    op.drop_table("spend_anomalies")
    op.drop_index(
        "uq_scheduler_runs_idempotency_key",
        table_name="scheduler_runs",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index(
        "ix_scheduler_runs_claim",
        table_name="scheduler_runs",
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.drop_table("scheduler_runs")
    op.drop_index("ix_provider_sync_runs_org_provider_started", table_name="provider_sync_runs")
    op.drop_table("provider_sync_runs")
    op.drop_table("provider_invoices")
    op.drop_table("provider_credentials")
    op.drop_table("owner_assignments")
    op.drop_table("credit_prices")
    op.drop_table("webhook_destinations")
    op.drop_index("ix_webhook_deliveries_org_status_next", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_table("teams")
    op.drop_table("spend_budgets")
    op.drop_table("signal_snoozes")
    op.drop_index("ix_signal_reads_organization_id", table_name="signal_reads")
    op.drop_table("signal_reads")
    op.drop_index("ix_signal_events_org_entity", table_name="signal_events")
    op.drop_index("ix_signal_events_org_closed_at", table_name="signal_events")
    op.drop_table("signal_events")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_provider_models_seen_org_last", table_name="provider_models_seen")
    op.drop_table("provider_models_seen")
    op.drop_index(
        "uq_provider_accounts_external_id",
        table_name="provider_accounts",
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.drop_table("provider_accounts")
    op.drop_table("personal_key_assignments")
    op.drop_table("organization_members")
    op.drop_index(
        "uq_organization_invitations_pending",
        table_name="organization_invitations",
        postgresql_where="accepted_at IS NULL AND revoked_at IS NULL",
    )
    op.drop_table("organization_invitations")
    op.drop_table("anomaly_settings")
    op.drop_table("worker_heartbeats")
    op.drop_table("users")
    op.drop_table("organizations")
    op.drop_index(op.f("ix_oidc_authorizations_expires_at"), table_name="oidc_authorizations")
    op.drop_table("oidc_authorizations")
    op.drop_index("ix_audit_events_org_created", table_name="audit_events")
    op.drop_table("audit_events")
