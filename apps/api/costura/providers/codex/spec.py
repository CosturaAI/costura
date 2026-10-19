"""The Codex analytics connector spec."""

from datetime import UTC, datetime, timedelta

from costura.config import Settings
from costura.providers.codex import PROVIDER as CODEX
from costura.providers.codex import client as codex_client
from costura.providers.codex import inventory as codex_inventory
from costura.providers.codex import sync as codex_sync
from costura.providers.spec import AccountInfo, ProviderSpec


def _codex_factory(
    settings: Settings, key: str, workspace_id: str | None = None
) -> codex_client.CodexAnalyticsClient:
    if workspace_id is None:
        raise ValueError("workspace_id is required for a Codex account")
    return codex_client.CodexAnalyticsClient(
        admin_key=key,
        workspace_id=workspace_id,
        base_url=settings.codex_base_url,
    )


def _codex_validate(client: codex_client.CodexAnalyticsClient) -> None:
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    next(client.usage_pages(end - timedelta(days=1), end, workspace=True, limit=1), None)


def _codex_account_info(client: codex_client.CodexAnalyticsClient) -> AccountInfo:
    return AccountInfo(external_id=client.workspace_id, name=None)


CODEX_SPEC = ProviderSpec(
    name=CODEX,
    label="Codex",
    vendor="OpenAI",
    surface="Codex",
    key_label="Admin API key",
    key_prefix="sk-admin-",
    console_label="OpenAI Admin Console",
    console_url="https://chatgpt.com/admin",
    env_var="CODEX_ADMIN_KEY",
    env_secret=lambda settings: settings.codex_admin_key,
    base_url_of=lambda settings: settings.codex_base_url,
    attribution="direct",
    cost_endpoint=codex_sync.ENDPOINT_COST,
    history_days=codex_client.MAX_LOOKBACK_DAYS,
    total_endpoint=codex_sync.ENDPOINT_COST_TOTAL,
    sync_steps=(
        ("cost", codex_sync.run_cost_sync),
        ("users", codex_sync.run_user_sync),
    ),
    allocation_inputs=("cost", "users"),
    data_endpoints=(codex_sync.ENDPOINT_COST, codex_sync.ENDPOINT_USER),
    client_factory=_codex_factory,
    validate=_codex_validate,
    run_inventory_sync=codex_inventory.run_inventory_sync,
    page_amount=codex_sync.page_credits,
    page_amount_with_params=codex_sync.page_amount_with_prices,
    auth_error=codex_client.CodexAuthError,
    api_error=codex_client.CodexApiError,
    account_info=_codex_account_info,
    env_account_id=lambda settings: settings.codex_workspace_id,
    requires_workspace=True,
    setup_pricing=True,
    user_attributed=True,
    credit_pricing=True,
)
