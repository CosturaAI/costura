"""The OpenAI Admin API connector spec."""

from costura.config import Settings
from costura.providers.openai import PROVIDER as OPENAI
from costura.providers.openai import client as openai_client
from costura.providers.openai import inventory as openai_inventory
from costura.providers.openai import sync as openai_sync
from costura.providers.spec import ProviderSpec


def _openai_factory(
    settings: Settings, key: str, _account_id: str | None = None
) -> openai_client.OpenAIAdminClient:
    return openai_client.OpenAIAdminClient(admin_key=key, base_url=settings.openai_base_url)


def _openai_validate(client: openai_client.OpenAIAdminClient) -> None:
    """An admin key that cannot list projects would leave the inventory empty and every
    project unnamed; the first projects page is the cheapest proof it can."""
    next(client.projects_pages(), None)


OPENAI_SPEC = ProviderSpec(
    name=OPENAI,
    label="OpenAI",
    vendor="OpenAI",
    surface="OpenAI Platform",
    key_label="admin key",
    key_prefix="sk-admin-",
    console_label="OpenAI platform",
    console_url="https://platform.openai.com/settings/organization/admin-keys",
    env_var="OPENAI_ADMIN_KEY",
    env_secret=lambda settings: settings.openai_admin_key,
    base_url_of=lambda settings: settings.openai_base_url,
    attribution="key_attributed",
    cost_endpoint=openai_sync.ENDPOINT_COST,
    total_endpoint=openai_sync.ENDPOINT_COST_TOTAL,
    sync_steps=(
        ("cost", openai_sync.run_cost_sync),
        ("total", openai_sync.run_cost_total_sync),
        ("keys", openai_sync.run_cost_by_key_sync),
        ("usage", openai_sync.run_usage_sync),
        ("usage_images", openai_sync.run_usage_images_sync),
        ("usage_embeddings", openai_sync.run_usage_embeddings_sync),
        ("usage_moderations", openai_sync.run_usage_moderations_sync),
        ("usage_audio_speeches", openai_sync.run_usage_audio_speeches_sync),
        ("usage_audio_transcriptions", openai_sync.run_usage_audio_transcriptions_sync),
        ("usage_vector_stores", openai_sync.run_usage_vector_stores_sync),
        (
            "usage_code_interpreter_sessions",
            openai_sync.run_usage_code_interpreter_sessions_sync,
        ),
    ),
    allocation_inputs=("cost", "usage"),
    data_endpoints=(
        openai_sync.ENDPOINT_COST,
        openai_sync.ENDPOINT_USAGE,
        *openai_sync.ACTIVITY_ENDPOINTS,
    ),
    client_factory=_openai_factory,
    validate=_openai_validate,
    run_inventory_sync=openai_inventory.run_inventory_sync,
    page_amount=openai_sync.page_amount,
    auth_error=openai_client.OpenAIAuthError,
    api_error=openai_client.OpenAIApiError,
    key_endpoint=openai_sync.ENDPOINT_COST_BY_KEY,
    key_amounts=openai_sync.key_amounts,
    activity_families=openai_sync.ACTIVITY_FAMILIES,
)
