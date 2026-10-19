import json

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import (
    ProviderApiKey,
    ProviderReportPage,
    ProviderSyncRun,
    ProviderUser,
    ProviderWorkspace,
    ProviderWorkspaceMember,
)
from costura.providers.anthropic.client import AnthropicAdminClient, AnthropicApiError
from costura.providers.anthropic.inventory import run_inventory_sync
from tests.conftest import ORG_ID, anthropic_fixture_handler, load_fixture, target


def _client(handler=anthropic_fixture_handler, **kwargs) -> AnthropicAdminClient:
    return AnthropicAdminClient(
        admin_key="sk-ant-admin01-test",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        **kwargs,
    )


def test_inventory_sync_populates_four_tables(db_session: Session) -> None:
    with _client() as client:
        summaries = run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), client)

    assert [s.endpoint for s in summaries] == [
        "workspaces",
        "users",
        "api_keys",
        "workspace_members",
    ]
    assert [(s.pages_fetched, s.items, s.rows_upserted) for s in summaries] == [
        (2, 2, 2),
        (1, 2, 2),
        (2, 3, 3),
        (1, 2, 2),
    ]
    assert summaries[3].skipped_workspaces == ["wrkspc_redacted_archived"]

    runs = db_session.scalars(select(ProviderSyncRun).order_by(ProviderSyncRun.id)).all()
    assert [r.status for r in runs] == ["succeeded"] * 4
    assert db_session.scalar(select(func.count()).select_from(ProviderReportPage)) == 6

    archived = db_session.scalars(
        select(ProviderWorkspace).where(ProviderWorkspace.external_id == "wrkspc_redacted_archived")
    ).one()
    assert archived.name == "Old experiments"
    assert archived.archived_at is not None
    platform = db_session.scalars(
        select(ProviderWorkspace).where(ProviderWorkspace.external_id == "wrkspc_redacted_a")
    ).one()
    assert platform.tags == {"team": "platform", "env": "production"}

    key = db_session.scalars(
        select(ProviderApiKey).where(ProviderApiKey.external_id == "apikey_redacted_2")
    ).one()
    assert key.name == "batch-ingest"
    assert key.workspace_external_id == "wrkspc_redacted_a"
    assert key.created_by_external_id == "user_redacted_bob"
    assert key.status == "active"
    assert key.expires_at is not None
    default_ws_key = db_session.scalars(
        select(ProviderApiKey).where(ProviderApiKey.external_id == "apikey_redacted_1")
    ).one()
    assert default_ws_key.workspace_external_id is None

    members = db_session.scalars(
        select(ProviderWorkspaceMember).order_by(ProviderWorkspaceMember.user_external_id)
    ).all()
    assert [(m.workspace_external_id, m.user_external_id, m.role) for m in members] == [
        ("wrkspc_redacted_a", "user_redacted_alice", "workspace_admin"),
        ("wrkspc_redacted_a", "user_redacted_bob", "workspace_developer"),
    ]
    members_page = db_session.scalars(
        select(ProviderReportPage).where(ProviderReportPage.endpoint == "workspace_members")
    ).one()
    assert members_page.request_params["workspace_id"] == "wrkspc_redacted_a"


def test_only_partial_key_hint_is_stored(db_session: Session) -> None:
    with _client() as client:
        run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), client)

    for key in db_session.scalars(select(ProviderApiKey)).all():
        assert key.partial_key_hint is not None
        assert key.partial_key_hint.startswith("sk-ant-api03-...")
        assert len(key.partial_key_hint) <= 24
    for page in db_session.scalars(
        select(ProviderReportPage).where(ProviderReportPage.endpoint == "api_keys")
    ):
        dumped = json.dumps(page.payload)
        assert "sk-ant-api03-..." in dumped
        assert "sk-ant-admin" not in dumped


def test_second_run_is_idempotent_and_marks_missing(db_session: Session) -> None:
    with _client() as client:
        run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), client)
    first_seen = {
        k.external_id: (k.first_seen_at, k.sync_run_id)
        for k in db_session.scalars(select(ProviderApiKey)).all()
    }
    db_session.expire_all()

    def without_key_3(request: httpx.Request) -> httpx.Response:
        response = anthropic_fixture_handler(request)
        if request.url.path.endswith("/api_keys") and "after_id" in str(request.url.query):
            payload = load_fixture("api_keys_page2.json")
            payload["data"] = [i for i in payload["data"] if i["id"] != "apikey_redacted_3"]
            return httpx.Response(200, json=payload)
        return response

    with _client(without_key_3) as client:
        summaries = run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), client)

    keys_summary = summaries[2]
    assert (keys_summary.items, keys_summary.rows_upserted) == (2, 2)
    assert db_session.scalar(select(func.count()).select_from(ProviderApiKey)) == 3
    keys = {k.external_id: k for k in db_session.scalars(select(ProviderApiKey)).all()}
    assert keys["apikey_redacted_3"].missing_since is not None
    assert keys["apikey_redacted_1"].missing_since is None
    assert keys["apikey_redacted_1"].first_seen_at == first_seen["apikey_redacted_1"][0]
    assert keys["apikey_redacted_1"].sync_run_id != first_seen["apikey_redacted_1"][1]
    assert db_session.scalar(select(func.count()).select_from(ProviderUser)) == 2
    db_session.expire_all()

    with _client() as client:
        run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), client)

    restored = db_session.scalars(
        select(ProviderApiKey).where(ProviderApiKey.external_id == "apikey_redacted_3")
    ).one()
    assert restored.missing_since is None
    assert db_session.scalar(select(func.count()).select_from(ProviderSyncRun)) == 12


def test_skipped_workspace_members_are_not_marked_missing(db_session: Session) -> None:
    with _client() as client:
        run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), client)

    def archived_readable(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/wrkspc_redacted_archived/members"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "user_id": "user_redacted_bob",
                            "workspace_id": "wrkspc_redacted_archived",
                            "workspace_role": "workspace_admin",
                        }
                    ],
                    "has_more": False,
                    "last_id": "user_redacted_bob",
                },
            )
        return anthropic_fixture_handler(request)

    with _client(archived_readable) as client:
        run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), client)
    assert db_session.scalar(select(func.count()).select_from(ProviderWorkspaceMember)) == 3

    with _client() as client:
        summary = run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), client)[3]

    assert summary.skipped_workspaces == ["wrkspc_redacted_archived"]
    archived_member = db_session.scalars(
        select(ProviderWorkspaceMember).where(
            ProviderWorkspaceMember.workspace_external_id == "wrkspc_redacted_archived"
        )
    ).one()
    assert archived_member.missing_since is None


def test_failure_marks_run_failed_and_stops(db_session: Session) -> None:
    def users_down(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/organizations/users"):
            return httpx.Response(503, json={"error": "down"})
        return anthropic_fixture_handler(request)

    with _client(users_down, max_retries=0) as client, pytest.raises(AnthropicApiError):
        run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), client)

    runs = db_session.scalars(select(ProviderSyncRun).order_by(ProviderSyncRun.id)).all()
    assert [(r.endpoint, r.status) for r in runs] == [
        ("workspaces", "succeeded"),
        ("users", "failed"),
    ]
    assert runs[1].error is not None and "503" in runs[1].error
    assert db_session.scalar(select(func.count()).select_from(ProviderWorkspace)) == 2
    assert db_session.scalar(select(func.count()).select_from(ProviderUser)) == 0
