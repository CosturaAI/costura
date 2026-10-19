from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import ProviderApiKey, ProviderUser, ProviderWorkspace
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.inventory import run_inventory_sync
from costura.providers.openrouter.client import OpenRouterManagementClient
from costura.providers.openrouter.inventory import run_inventory_sync as run_openrouter_inventory
from costura.spend.inventory import InventoryResolver
from tests.conftest import ORG_ID, account_of, target


def test_empty_inventory_keeps_raw_ids(db_session: Session) -> None:
    resolver = InventoryResolver(db_session, ORG_ID, "anthropic")

    assert resolver.workspace_label("anthropic", None) == "(default workspace)"
    assert resolver.workspace_label("anthropic", "wrkspc_x") == "wrkspc_x (not in inventory)"
    assert resolver.api_key_label("anthropic", None) == "(playground, no api key)"
    assert resolver.api_key_label("anthropic", "apikey_x") == "apikey_x (not in inventory)"
    assert resolver.workspace_admins("anthropic", "wrkspc_x") == []


def test_resolver_after_inventory_sync(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), anthropic_client)
    resolver = InventoryResolver(db_session, ORG_ID, "anthropic")

    assert (
        resolver.workspace_label("anthropic", "wrkspc_redacted_a") == "Platform (wrkspc_redacted_a)"
    )
    assert (
        resolver.workspace_label("anthropic", "wrkspc_redacted_archived")
        == "Old experiments (wrkspc_redacted_archived) [archived]"
    )
    assert resolver.workspace_admins("anthropic", "wrkspc_redacted_a") == ["alice@example.com"]
    assert resolver.workspace_admins("anthropic", None) == []

    key = resolver.api_key("anthropic", "apikey_redacted_2")
    assert key is not None
    assert (key.name, key.partial_key_hint, key.status) == (
        "batch-ingest",
        "sk-ant-api03-...bbbb",
        "active",
    )
    assert resolver.user_email("anthropic", key.created_by_external_id) == "bob@example.com"
    assert (
        resolver.api_key_label("anthropic", "apikey_redacted_1")
        == "billing-agent (apikey_redacted_1)"
    )
    assert resolver.user_email("anthropic", None) == ""
    assert resolver.user_email("anthropic", "user_unknown") == "user_unknown (not in inventory)"
    assert resolver.creator_of("anthropic", "apikey_redacted_2") == "user_redacted_bob"
    assert resolver.creator_of("anthropic", "apikey_redacted_3") is None
    assert resolver.creator_of("anthropic", "apikey_unknown") is None
    assert resolver.account_label("anthropic", None) == "(api key request)"
    assert resolver.account_label("anthropic", "user_redacted_alice") == "alice@example.com"


def test_all_scope_resolves_colliding_provider_ids_independently(
    db_session: Session,
    anthropic_client: AnthropicAdminClient,
    openrouter_client: OpenRouterManagementClient,
) -> None:
    run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), anthropic_client)
    run_openrouter_inventory(
        db_session, target(db_session, ORG_ID, "openrouter"), openrouter_client
    )
    workspace = db_session.scalar(
        select(ProviderWorkspace).where(ProviderWorkspace.provider == "openrouter").limit(1)
    )
    key = db_session.scalar(
        select(ProviderApiKey).where(ProviderApiKey.provider == "openrouter").limit(1)
    )
    assert workspace is not None and key is not None
    user = db_session.scalar(
        select(ProviderUser).where(ProviderUser.provider == "openrouter").limit(1)
    )
    if user is None:
        user = ProviderUser(
            organization_id=ORG_ID,
            provider="openrouter",
            provider_account_id=account_of(db_session, ORG_ID, "openrouter"),
            sync_run_id=key.sync_run_id,
            external_id="temporary-user",
            email="temporary@example.com",
            role="member",
        )
        db_session.add(user)
    workspace.external_id = "wrkspc_redacted_a"
    workspace.name = "OpenRouter workspace"
    user.external_id = "user_redacted_bob"
    user.email = "openrouter@example.com"
    key.external_id = "apikey_redacted_2"
    key.name = "openrouter-key"
    key.workspace_external_id = workspace.external_id
    key.created_by_external_id = user.external_id
    db_session.commit()

    resolver = InventoryResolver(db_session, ORG_ID, "all")

    assert resolver.workspace_label("anthropic", workspace.external_id).startswith("Platform")
    assert resolver.workspace_label("openrouter", workspace.external_id).startswith(
        "OpenRouter workspace"
    )
    assert resolver.api_key_label("anthropic", key.external_id).startswith("batch-ingest")
    assert resolver.api_key_label("openrouter", key.external_id).startswith("openrouter-key")
    assert resolver.user_email("anthropic", user.external_id) == "bob@example.com"
    assert resolver.user_email("openrouter", user.external_id) == "openrouter@example.com"
