"""The Claude.ai analytics connector spec."""

from datetime import UTC, datetime, timedelta

from costura.config import Settings
from costura.providers.claude_ai import PROVIDER as CLAUDE_AI
from costura.providers.claude_ai import client as claude_ai_client
from costura.providers.claude_ai import inventory as claude_ai_inventory
from costura.providers.claude_ai import sync as claude_ai_sync
from costura.providers.spec import ProviderSpec


def _claude_ai_factory(
    settings: Settings, key: str, _account_id: str | None = None
) -> claude_ai_client.ClaudeAiAnalyticsClient:
    return claude_ai_client.ClaudeAiAnalyticsClient(
        api_key=key, base_url=settings.claude_ai_base_url
    )


def _claude_ai_validate(client: claude_ai_client.ClaudeAiAnalyticsClient) -> None:
    next(
        client.users_pages(activity_date=datetime.now(UTC).date() - timedelta(days=2), limit=1),
        None,
    )


CLAUDE_AI_SPEC = ProviderSpec(
    name=CLAUDE_AI,
    label="Claude.ai",
    vendor="Anthropic",
    surface="claude.ai",
    key_label="analytics API key",
    key_prefix="sk-ant-api01-",
    console_label="Claude admin",
    console_url="https://claude.ai/admin-settings",
    env_var="CLAUDE_AI_API_KEY",
    env_secret=lambda settings: settings.claude_ai_api_key,
    base_url_of=lambda settings: settings.claude_ai_base_url,
    attribution="direct",
    cost_endpoint=claude_ai_sync.ENDPOINT_COST,
    total_endpoint=claude_ai_sync.ENDPOINT_COST_TOTAL,
    sync_steps=(
        ("cost", claude_ai_sync.run_cost_sync),
        ("total", claude_ai_sync.run_cost_total_sync),
        ("users", claude_ai_sync.run_user_sync),
    ),
    allocation_inputs=("cost", "users"),
    data_endpoints=(claude_ai_sync.ENDPOINT_COST, claude_ai_sync.ENDPOINT_USER),
    client_factory=_claude_ai_factory,
    validate=_claude_ai_validate,
    run_inventory_sync=claude_ai_inventory.run_inventory_sync,
    page_amount=claude_ai_sync.page_amount_for_reconcile,
    auth_error=claude_ai_client.ClaudeAiAuthError,
    api_error=claude_ai_client.ClaudeAiApiError,
    user_attributed=True,
    pooled_seats=True,
)
