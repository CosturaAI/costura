import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import (
    ProviderModelSeen,
    ProviderSyncRun,
    ProviderUser,
    SpendAllocatedLine,
    SpendCostLine,
    SpendUsageLine,
)
from costura.providers.claude_ai import PROVIDER
from costura.providers.claude_ai.client import (
    ClaudeAiAnalyticsClient,
)
from costura.providers.claude_ai.inventory import run_inventory_sync
from costura.providers.claude_ai.sync import (
    ENDPOINT_COST,
    ENDPOINT_USER,
    run_cost_sync,
    run_cost_total_sync,
    run_user_sync,
)
from costura.spend.allocate import run_allocation
from costura.spend.allocation_split import REASON_NO_USER
from costura.spend.query import QuerySpec, query_spend
from costura.spend.reconcile import reconcile
from costura.spend.window import Window
from tests.conftest import ORG_ID, target

FIXTURES = Path(__file__).parent / "fixtures" / "claude_ai"
START = datetime(2026, 9, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
WATERMARK = datetime(2026, 9, 3, 12, tzinfo=UTC)
ORG_TOTAL = Decimal("3.58456790")
LIST_TOTAL = Decimal("4.46320987")
USER_TOTAL = Decimal("2.70000000")
NO_SLEEP = lambda _: None  # noqa: E731


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def synced(db_session: Session, claude_ai_client: ClaudeAiAnalyticsClient) -> Window:
    unit = target(db_session, ORG_ID, PROVIDER)
    run_inventory_sync(db_session, unit, claude_ai_client)
    run_cost_sync(db_session, unit, claude_ai_client, START, END)
    run_cost_total_sync(db_session, unit, claude_ai_client, START, END)
    run_user_sync(db_session, unit, claude_ai_client, START, END)
    window = Window(start=START, end=END)
    run_allocation(db_session, ORG_ID, PROVIDER, window, account_id=unit.account_id)
    return window


def test_normalize_sync_inventory_and_watermark(db_session: Session, synced: Window) -> None:
    costs = list(db_session.scalars(select(SpendCostLine).order_by(SpendCostLine.period_start)))
    usage = list(
        db_session.scalars(
            select(SpendUsageLine).order_by(SpendUsageLine.period_start, SpendUsageLine.account_id)
        )
    )

    assert len(costs) == 5
    assert sum((Decimal(line.amount) for line in costs), Decimal("0")) == ORG_TOTAL
    assert sum((Decimal(line.list_amount or 0) for line in costs), Decimal("0")) == LIST_TOTAL
    assert {line.description for line in costs} == {"chat", "claude_code", "other"}
    remainder = next(line for line in costs if line.cost_type == "org_remainder")
    assert Decimal(remainder.amount) == Decimal("0.10")
    assert Decimal(remainder.list_amount or 0) == Decimal("0.12")
    assert {line.service_tier for line in costs} == {"standard", "fast", None}
    assert all(line.period_end <= WATERMARK for line in costs)
    assert len(usage) == 3
    assert sum((Decimal(line.amount or 0) for line in usage), Decimal("0")) == USER_TOTAL
    alpha = next(
        line for line in usage if line.account_id == "user_alpha" and line.product == "chat"
    )
    assert alpha.uncached_input_tokens == 1000
    assert alpha.cache_creation_5m_tokens == 200
    assert alpha.output_tokens == 300

    assert {
        (user.external_id, user.email) for user in db_session.scalars(select(ProviderUser))
    } == {
        ("user_alpha", "alpha@example.com"),
        ("user_beta", "beta@example.com"),
    }
    assert {row.model for row in db_session.scalars(select(ProviderModelSeen))} == {
        "claude-opus-5",
        "claude-sonnet-4-6",
    }
    watermarks = set(
        db_session.scalars(
            select(ProviderSyncRun.data_refreshed_at).where(
                ProviderSyncRun.endpoint.in_((ENDPOINT_COST, ENDPOINT_USER))
            )
        )
    )
    assert watermarks == {WATERMARK}


def test_direct_allocation_remainder_origin_list_and_reconcile(
    db_session: Session, synced: Window
) -> None:
    rows = list(db_session.scalars(select(SpendAllocatedLine)))
    assert sum((Decimal(row.amount) for row in rows), Decimal("0")) == ORG_TOTAL
    assert (
        sum(
            (Decimal(row.amount) for row in rows if row.unallocated_reason is None),
            Decimal("0"),
        )
        == USER_TOTAL
    )
    assert (
        sum(
            (Decimal(row.amount) for row in rows if row.unallocated_reason == REASON_NO_USER),
            Decimal("0"),
        )
        == ORG_TOTAL - USER_TOTAL
    )
    assert {row.description for row in rows} == {"chat", "claude_code", "other"}

    origin = query_spend(
        db_session,
        org_id=ORG_ID,
        spec=QuerySpec(
            measure="billed_usd",
            dimensions=("origin",),
            filters={"origin": "claude.ai"},
            start=date(2026, 9, 1),
            end=date(2026, 9, 3),
            interval="month",
            top=10,
        ),
    )
    assert origin.series[0].keys == {"origin": "claude.ai"}
    assert origin.series[0].total == ORG_TOTAL

    assert {
        row.labels["model_channel"]
        for row in query_spend(
            db_session,
            org_id=ORG_ID,
            spec=QuerySpec(
                measure="billed_usd",
                dimensions=("model_channel",),
                filters={"provider": PROVIDER},
                start=date(2026, 9, 1),
                end=date(2026, 9, 3),
                interval="month",
                top=10,
            ),
        ).series
    } == {"Claude.ai"}

    report = reconcile(
        db_session,
        org_id=ORG_ID,
        provider=PROVIDER,
        window=synced,
        reported_total=ORG_TOTAL,
    )
    assert report.data_refreshed_at == WATERMARK
    assert report.user_attributed_total == USER_TOTAL
    assert report.user_unattributed_total == ORG_TOTAL - USER_TOTAL
    assert report.provider_matches is True


def test_api_exposes_watermark_and_user_reconciliation(
    client: TestClient, db_session: Session, synced: Window
) -> None:
    response = client.get("/api/v1/orgs/default/providers/claude_ai/months/2026-09/reconcile")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data_refreshed_at"] == "2026-09-03T12:00:00Z"
    assert body["user_attributed_total"] == "2.70"
    assert body["user_unattributed_total"] == "0.88"
    assert body["provider_check"]["ok"] is True
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SpendCostLine)
            .where(SpendCostLine.period_start >= datetime(2026, 9, 3, tzinfo=UTC))
        )
        == 0
    )
