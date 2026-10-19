"""Codex users are inventoried from the per-user daily usage report."""

from sqlalchemy.orm import Session

from costura.providers.codex.client import CodexAnalyticsClient
from costura.providers.runs import InventorySummary, Target


def run_inventory_sync(
    _session: Session, _target: Target, _client: CodexAnalyticsClient
) -> list[InventorySummary]:
    return []


__all__ = ["run_inventory_sync"]
