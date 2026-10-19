"""The OpenRouter management API connector spec."""

from costura.config import Settings
from costura.providers.openrouter import PROVIDER as OPENROUTER
from costura.providers.openrouter import client as openrouter_client
from costura.providers.openrouter import inventory as openrouter_inventory
from costura.providers.openrouter import sync as openrouter_sync
from costura.providers.spec import AccountInfo, NotManagementKey, ProviderSpec


def _openrouter_factory(
    settings: Settings, key: str, _account_id: str | None = None
) -> openrouter_client.OpenRouterManagementClient:
    return openrouter_client.OpenRouterManagementClient(
        management_key=key, base_url=settings.openrouter_base_url
    )


def _openrouter_validate(client: openrouter_client.OpenRouterManagementClient) -> None:
    if client.current_key().get("is_management_key") is not True:
        raise NotManagementKey(
            "the key is a regular API key; the management API needs a management key "
            "(Settings, Management keys in the OpenRouter console)"
        )


def _openrouter_account_info(
    client: openrouter_client.OpenRouterManagementClient,
) -> AccountInfo | None:
    """OpenRouter names no organization; the management key's own label stands in."""
    label = client.current_key().get("label")
    return AccountInfo(
        external_id=None, name=label if isinstance(label, str) and label.strip() else None
    )


OPENROUTER_SPEC = ProviderSpec(
    name=OPENROUTER,
    label="OpenRouter",
    vendor="OpenRouter",
    surface="OpenRouter",
    key_label="management key",
    key_prefix="sk-or-v1-",
    console_label="OpenRouter console",
    console_url="https://openrouter.ai/settings/management-keys",
    keys_console_url="https://openrouter.ai/settings/keys",
    env_var="OPENROUTER_ADMIN_KEY",
    env_secret=lambda settings: settings.openrouter_admin_key,
    base_url_of=lambda settings: settings.openrouter_base_url,
    attribution="direct",
    cost_endpoint=openrouter_sync.ENDPOINT_COST,
    total_endpoint=openrouter_sync.ENDPOINT_COST_TOTAL,
    sync_steps=(
        ("cost", openrouter_sync.run_cost_sync),
        ("total", openrouter_sync.run_cost_total_sync),
    ),
    allocation_inputs=("cost",),
    data_endpoints=(openrouter_sync.ENDPOINT_COST,),
    client_factory=_openrouter_factory,
    validate=_openrouter_validate,
    run_inventory_sync=openrouter_inventory.run_inventory_sync,
    page_amount=openrouter_sync.page_amount,
    auth_error=openrouter_client.OpenRouterAuthError,
    api_error=openrouter_client.OpenRouterApiError,
    account_info=_openrouter_account_info,
)
