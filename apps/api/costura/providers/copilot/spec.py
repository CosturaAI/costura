"""The GitHub Copilot connector spec, `experimental` until a live organization confirms
it."""

from costura.config import Settings
from costura.providers.copilot import PROVIDER as COPILOT
from costura.providers.copilot import client as copilot_client
from costura.providers.copilot import inventory as copilot_inventory
from costura.providers.copilot import sync as copilot_sync
from costura.providers.spec import AccountInfo, ProviderSpec


def _copilot_factory(
    settings: Settings, key: str, org: str | None = None
) -> copilot_client.GitHubBillingClient:
    if org is None:
        raise ValueError("the GitHub organization login is required for a Copilot account")
    return copilot_client.GitHubBillingClient(
        token=key, org=org, base_url=settings.copilot_base_url
    )


def _copilot_validate(client: copilot_client.GitHubBillingClient) -> None:
    next(client.seats_pages(), None)


def _copilot_account_info(client: copilot_client.GitHubBillingClient) -> AccountInfo:
    return AccountInfo(external_id=client.org, name=client.org)


COPILOT_SPEC = ProviderSpec(
    name=COPILOT,
    label="GitHub Copilot",
    vendor="GitHub",
    surface="GitHub Copilot",
    key_label="personal access token (classic) of an organization owner or billing manager",
    key_prefix="ghp_",
    console_label="GitHub organization settings",
    console_url="https://github.com/settings/tokens",
    env_var="COPILOT_GITHUB_TOKEN",
    env_secret=lambda settings: settings.copilot_github_token,
    base_url_of=lambda settings: settings.copilot_base_url,
    attribution="direct",
    cost_endpoint=copilot_sync.ENDPOINT_COST,
    history_days=copilot_client.MAX_LOOKBACK_DAYS,
    total_endpoint=copilot_sync.ENDPOINT_COST_TOTAL,
    sync_steps=(
        ("cost", copilot_sync.run_cost_sync),
        ("users", copilot_sync.run_user_sync),
    ),
    allocation_inputs=("cost", "users"),
    data_endpoints=(copilot_sync.ENDPOINT_COST, copilot_sync.ENDPOINT_USERS),
    client_factory=_copilot_factory,
    validate=_copilot_validate,
    run_inventory_sync=copilot_inventory.run_inventory_sync,
    page_amount=copilot_sync.page_amount,
    page_amount_with_params=copilot_sync.page_amount_with_params,
    auth_error=copilot_client.CopilotAuthError,
    api_error=copilot_client.CopilotApiError,
    account_info=_copilot_account_info,
    env_account_id=lambda settings: settings.copilot_org,
    requires_workspace=True,
    login_mapping=True,
    experimental=True,
)
