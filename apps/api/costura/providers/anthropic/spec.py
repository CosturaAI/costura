"""The Anthropic Admin API connector spec."""

from costura.config import Settings
from costura.providers.anthropic import PROVIDER as ANTHROPIC
from costura.providers.anthropic import client as anthropic_client
from costura.providers.anthropic import inventory as anthropic_inventory
from costura.providers.anthropic import sync as anthropic_sync
from costura.providers.spec import AccountInfo, ProviderSpec


def _anthropic_factory(
    settings: Settings, key: str, _account_id: str | None = None
) -> anthropic_client.AnthropicAdminClient:
    return anthropic_client.AnthropicAdminClient(
        admin_key=key, base_url=settings.anthropic_base_url
    )


def _anthropic_validate(client: anthropic_client.AnthropicAdminClient) -> None:
    next(client.workspaces_pages(include_archived=False), None)


def _anthropic_account_info(client: anthropic_client.AnthropicAdminClient) -> AccountInfo | None:
    record = client.organization()
    external_id = record.get("id")
    name = record.get("name")
    return AccountInfo(
        external_id=external_id if isinstance(external_id, str) and external_id else None,
        name=name if isinstance(name, str) and name.strip() else None,
    )


ANTHROPIC_SPEC = ProviderSpec(
    name=ANTHROPIC,
    label="Anthropic",
    vendor="Anthropic",
    surface="Claude Platform",
    key_label="admin key",
    key_prefix="sk-ant-admin",
    console_label="Anthropic Console",
    console_url="https://console.anthropic.com/settings/admin-keys",
    env_var="ANTHROPIC_ADMIN_KEY",
    env_secret=lambda settings: settings.anthropic_admin_key,
    base_url_of=lambda settings: settings.anthropic_base_url,
    attribution="token_share",
    cost_endpoint=anthropic_sync.ENDPOINT_COST,
    total_endpoint=anthropic_sync.ENDPOINT_COST_TOTAL,
    sync_steps=(
        ("cost", anthropic_sync.run_cost_sync),
        ("total", anthropic_sync.run_cost_total_sync),
        ("usage", anthropic_sync.run_usage_sync),
    ),
    allocation_inputs=("cost", "usage"),
    data_endpoints=(anthropic_sync.ENDPOINT_COST, anthropic_sync.ENDPOINT_USAGE),
    client_factory=_anthropic_factory,
    validate=_anthropic_validate,
    run_inventory_sync=anthropic_inventory.run_inventory_sync,
    page_amount=anthropic_sync.page_amount,
    auth_error=anthropic_client.AnthropicAuthError,
    api_error=anthropic_client.AnthropicApiError,
    account_info=_anthropic_account_info,
    personal_session_keys=True,
    login_usage_label="(Claude Code logins, no API key)",
)
