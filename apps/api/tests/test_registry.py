"""Provider registry: specs, scope resolution, credential dispatch, two-provider scheduler."""

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import credentials, scheduler, secrets
from costura.config import get_settings
from costura.models.scheduler import SchedulerRun
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.claude_ai.client import ClaudeAiAnalyticsClient
from costura.providers.cursor.client import CursorAdminClient
from costura.providers.openai.client import OpenAIAdminClient
from costura.providers.openrouter.client import OpenRouterManagementClient
from costura.providers.registry import (
    ALL,
    PROVIDERS,
    get_spec,
    provider_names,
    resolve_scope,
)
from tests.conftest import (
    account_of,
    anthropic_fixture_handler,
    cursor_fixture_handler,
    openai_fixture_handler,
    openrouter_fixture_handler,
)

NO_SLEEP = lambda _: None  # noqa: E731


def _factory(key: str):
    if key.startswith("key_"):
        return CursorAdminClient(
            api_key=key, transport=httpx.MockTransport(cursor_fixture_handler), sleep=NO_SLEEP
        )
    if key.startswith("sk-admin-"):
        return OpenAIAdminClient(
            admin_key=key, transport=httpx.MockTransport(openai_fixture_handler), sleep=NO_SLEEP
        )
    if key.startswith("sk-or-"):
        return OpenRouterManagementClient(
            management_key=key,
            transport=httpx.MockTransport(openrouter_fixture_handler),
            sleep=NO_SLEEP,
        )
    return AnthropicAdminClient(
        admin_key=key, transport=httpx.MockTransport(anthropic_fixture_handler), sleep=NO_SLEEP
    )


@pytest.fixture
def secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(secrets.generate_key()))
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", None)


def test_registry_lists_every_provider_with_its_policies() -> None:
    assert provider_names() == (
        "anthropic",
        "claude_ai",
        "codex",
        "openrouter",
        "openai",
        "cursor",
        "copilot",
    )
    anthropic, openrouter = PROVIDERS["anthropic"], PROVIDERS["openrouter"]
    openai = PROVIDERS["openai"]
    cursor = PROVIDERS["cursor"]
    claude_ai = PROVIDERS["claude_ai"]
    codex = PROVIDERS["codex"]
    assert anthropic.attribution == "token_share" and openrouter.attribution == "direct"
    assert openai.attribution == "key_attributed"
    assert cursor.attribution == "direct"
    assert claude_ai.attribution == "direct"
    assert codex.attribution == "direct"
    assert {name: (spec.vendor, spec.surface) for name, spec in PROVIDERS.items()} == {
        "anthropic": ("Anthropic", "Claude Platform"),
        "claude_ai": ("Anthropic", "claude.ai"),
        "codex": ("OpenAI", "Codex"),
        "openrouter": ("OpenRouter", "OpenRouter"),
        "openai": ("OpenAI", "OpenAI Platform"),
        "cursor": ("Cursor", "Cursor"),
        "copilot": ("GitHub", "GitHub Copilot"),
    }
    assert anthropic.key_prefix == "sk-ant-admin" and openrouter.key_prefix == "sk-or-v1-"
    assert openai.key_prefix == "sk-admin-"
    assert [name for name, _ in anthropic.sync_steps] == ["cost", "total", "usage"]
    assert [name for name, _ in claude_ai.sync_steps] == ["cost", "total", "users"]
    assert [name for name, _ in codex.sync_steps] == ["cost", "users"]
    assert [name for name, _ in openrouter.sync_steps] == ["cost", "total"]
    assert [name for name, _ in openai.sync_steps] == [
        "cost",
        "total",
        "keys",
        "usage",
        "usage_images",
        "usage_embeddings",
        "usage_moderations",
        "usage_audio_speeches",
        "usage_audio_transcriptions",
        "usage_vector_stores",
        "usage_code_interpreter_sessions",
    ]
    assert [name for name, _ in cursor.sync_steps] == ["cost", "seats", "total"]
    assert anthropic.allocation_inputs == ("cost", "usage") and openai.allocation_inputs == (
        "cost",
        "usage",
    )
    assert openrouter.allocation_inputs == ("cost",)
    assert cursor.allocation_inputs == ("cost", "seats")
    assert anthropic.data_endpoints == ("cost_report", "usage_report_messages")
    assert openrouter.data_endpoints == ("analytics_cost",)
    assert openai.data_endpoints == (
        "costs",
        "usage_completions",
        "usage_images",
        "usage_embeddings",
        "usage_moderations",
        "usage_audio_speeches",
        "usage_audio_transcriptions",
        "usage_vector_stores",
        "usage_code_interpreter_sessions",
    )
    assert openrouter.env_var == "OPENROUTER_ADMIN_KEY"
    assert openai.env_var == "OPENAI_ADMIN_KEY"
    assert cursor.env_var == "CURSOR_API_KEY"
    assert cursor.data_endpoints == ("filtered_usage_events", "daily_usage_seats")
    assert resolve_scope(ALL) == (
        "anthropic",
        "claude_ai",
        "codex",
        "openrouter",
        "openai",
        "cursor",
        "copilot",
    )
    assert resolve_scope("openrouter") == ("openrouter",)
    with pytest.raises(KeyError, match="unknown provider"):
        get_spec("bedrock")


def test_client_factory_builds_read_only_clients_from_settings() -> None:
    settings = get_settings()
    with PROVIDERS["openrouter"].client_factory(settings, "sk-or-v1-x") as client:
        assert isinstance(client, OpenRouterManagementClient)
    with PROVIDERS["anthropic"].client_factory(settings, "sk-ant-admin01-x") as client:
        assert isinstance(client, AnthropicAdminClient)
    with PROVIDERS["claude_ai"].client_factory(settings, "sk-ant-admin01-x") as client:
        assert isinstance(client, ClaudeAiAnalyticsClient)
    with PROVIDERS["openai"].client_factory(settings, "sk-admin-x") as client:
        assert isinstance(client, OpenAIAdminClient)
    with PROVIDERS["cursor"].client_factory(settings, "key_x") as client:
        assert isinstance(client, CursorAdminClient)


def test_openrouter_validation_requires_a_management_key(
    db_session: Session, org_id: int, secret_key: None
) -> None:
    with pytest.raises(credentials.InvalidCredential, match="management key"):
        credentials.set_credential(
            db_session, get_settings(), org_id, "openrouter", "sk-or-v1-regular", factory=_factory
        )
    row = credentials.set_credential(
        db_session, get_settings(), org_id, "openrouter", "sk-or-v1-mgmt", factory=_factory
    )
    assert row.provider == "openrouter" and row.key_hint == "mgmt"
    conn = credentials.connection(
        db_session,
        get_settings(),
        org_id,
        "openrouter",
        account_of(db_session, org_id, "openrouter"),
    )
    assert conn.connected and conn.source == "stored"


def test_cursor_connection_validates_members_endpoint(
    db_session: Session, org_id: int, secret_key: None
) -> None:
    row = credentials.set_credential(
        db_session, get_settings(), org_id, "cursor", "key_team", factory=_factory
    )
    assert row.provider == "cursor" and row.key_hint == "team"
    conn = credentials.connection(
        db_session,
        get_settings(),
        org_id,
        "cursor",
        account_of(db_session, org_id, "cursor"),
    )
    assert conn.connected and conn.source == "stored"


def test_environment_fallback_is_per_provider(
    db_session: Session, org_id: int, secret_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(credentials.NoCredential, match="OpenRouter management key"):
        credentials.resolve_key(
            db_session,
            get_settings(),
            org_id,
            "openrouter",
            account_of(db_session, org_id, "openrouter"),
        )
    monkeypatch.setattr(get_settings(), "openrouter_admin_key", SecretStr("sk-or-v1-env1"))
    assert credentials.resolve_key(
        db_session,
        get_settings(),
        org_id,
        "openrouter",
        account_of(db_session, org_id, "openrouter"),
    ) == (
        "sk-or-v1-env1",
        "environment",
    )
    with pytest.raises(credentials.NoCredential, match="Anthropic admin key"):
        credentials.resolve_key(
            db_session,
            get_settings(),
            org_id,
            "anthropic",
            account_of(db_session, org_id, "anthropic"),
        )
    assert scheduler.target_organizations(db_session, get_settings(), provider="openrouter") == [
        org_id
    ]
    assert scheduler.target_organizations(db_session, get_settings(), provider="anthropic") == []


def test_run_cycle_covers_every_provider_the_organization_has_a_key_for(
    db_session: Session, org_id: int, secret_key: None
) -> None:
    credentials.set_credential(
        db_session, get_settings(), org_id, "anthropic", "sk-ant-admin01-t", factory=_factory
    )
    credentials.set_credential(
        db_session, get_settings(), org_id, "openrouter", "sk-or-v1-t", factory=_factory
    )

    results = scheduler.run_cycle(db_session, get_settings(), factory=_factory, sleep=NO_SLEEP)

    assert [(r.provider, r.status) for r in results] == [
        ("anthropic", "succeeded"),
        ("openrouter", "succeeded"),
    ]
    openrouter = results[1]
    assert [s.step for s in openrouter.steps][:5] == ["inventory", "cost", "total", "cost", "total"]
    assert {s.step for s in openrouter.steps} >= {"allocate", "detect", "project", "budgets"}
    rows = list(db_session.scalars(select(SchedulerRun).order_by(SchedulerRun.id)))
    assert [r.provider for r in rows] == ["anthropic", "openrouter"]

    # Today's openrouter run already succeeded, so a second pass does not execute it again.
    credentials.clear_credential(
        db_session, org_id, "anthropic", account_of(db_session, org_id, "anthropic")
    )
    again = scheduler.run_cycle(
        db_session, get_settings(), org_ids=[org_id], factory=_factory, sleep=NO_SLEEP
    )
    assert again == []
    rows = list(db_session.scalars(select(SchedulerRun).order_by(SchedulerRun.id)))
    assert [(r.provider, r.status) for r in rows] == [
        ("anthropic", "succeeded"),
        ("openrouter", "succeeded"),
    ]

    # Naming a provider without a key records the skipped cycle instead.
    named = scheduler.run_cycle(
        db_session,
        get_settings(),
        provider="anthropic",
        org_ids=[org_id],
        factory=_factory,
        sleep=NO_SLEEP,
    )
    assert [(r.provider, r.status) for r in named] == [
        ("anthropic", "skipped"),
    ]
