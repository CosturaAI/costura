"""index sync run references for retention

Revision ID: 1e0cf1dde539
Revises: 7ed3e699f8bc
Create Date: 2026-10-28 15:47:41.515225

"""

from collections.abc import Sequence

from alembic import op

revision: str = "1e0cf1dde539"
down_revision: str | Sequence[str] | None = "7ed3e699f8bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_provider_api_keys_sync_run_id"), "provider_api_keys", ["sync_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_provider_inventory_events_sync_run_id"),
        "provider_inventory_events",
        ["sync_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_limits_sync_run_id"), "provider_limits", ["sync_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_provider_report_pages_fetched_at"),
        "provider_report_pages",
        ["fetched_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_users_sync_run_id"), "provider_users", ["sync_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_provider_workspace_members_sync_run_id"),
        "provider_workspace_members",
        ["sync_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_workspaces_sync_run_id"),
        "provider_workspaces",
        ["sync_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_spend_activity_lines_sync_run_id"),
        "spend_activity_lines",
        ["sync_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_spend_cost_lines_sync_run_id"), "spend_cost_lines", ["sync_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_spend_usage_lines_sync_run_id"), "spend_usage_lines", ["sync_run_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_spend_usage_lines_sync_run_id"), table_name="spend_usage_lines")
    op.drop_index(op.f("ix_spend_cost_lines_sync_run_id"), table_name="spend_cost_lines")
    op.drop_index(op.f("ix_spend_activity_lines_sync_run_id"), table_name="spend_activity_lines")
    op.drop_index(op.f("ix_provider_workspaces_sync_run_id"), table_name="provider_workspaces")
    op.drop_index(
        op.f("ix_provider_workspace_members_sync_run_id"), table_name="provider_workspace_members"
    )
    op.drop_index(op.f("ix_provider_users_sync_run_id"), table_name="provider_users")
    op.drop_index(op.f("ix_provider_report_pages_fetched_at"), table_name="provider_report_pages")
    op.drop_index(op.f("ix_provider_limits_sync_run_id"), table_name="provider_limits")
    op.drop_index(
        op.f("ix_provider_inventory_events_sync_run_id"), table_name="provider_inventory_events"
    )
    op.drop_index(op.f("ix_provider_api_keys_sync_run_id"), table_name="provider_api_keys")
