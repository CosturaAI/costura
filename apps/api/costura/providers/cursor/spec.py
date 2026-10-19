"""The Cursor Admin API connector spec."""

from costura.config import Settings
from costura.providers.cursor import PROVIDER as CURSOR
from costura.providers.cursor import client as cursor_client
from costura.providers.cursor import inventory as cursor_inventory
from costura.providers.cursor import sync as cursor_sync
from costura.providers.spec import ProviderSpec


def _cursor_factory(
    settings: Settings, key: str, _account_id: str | None = None
) -> cursor_client.CursorAdminClient:
    return cursor_client.CursorAdminClient(api_key=key, base_url=settings.cursor_base_url)


def _cursor_validate(client: cursor_client.CursorAdminClient) -> None:
    next(client.members_pages(), None)


CURSOR_SPEC = ProviderSpec(
    name=CURSOR,
    label="Cursor",
    vendor="Cursor",
    surface="Cursor",
    key_label="team API key",
    key_prefix="key_",
    console_label="Cursor dashboard",
    console_url="https://cursor.com/dashboard?tab=integrations",
    env_var="CURSOR_API_KEY",
    env_secret=lambda settings: settings.cursor_api_key,
    base_url_of=lambda settings: settings.cursor_base_url,
    attribution="direct",
    cost_endpoint=cursor_sync.ENDPOINT_COST,
    total_endpoint=cursor_sync.ENDPOINT_COST_TOTAL,
    sync_steps=(
        ("cost", cursor_sync.run_cost_sync),
        ("seats", cursor_sync.run_seat_sync),
        ("total", cursor_sync.run_cost_total_sync),
    ),
    allocation_inputs=("cost", "seats"),
    data_endpoints=(cursor_sync.ENDPOINT_COST, cursor_sync.ENDPOINT_SEATS),
    client_factory=_cursor_factory,
    validate=_cursor_validate,
    run_inventory_sync=cursor_inventory.run_inventory_sync,
    page_amount=cursor_sync.page_amount,
    page_amount_with_params=cursor_sync.page_amount_with_settings,
    auth_error=cursor_client.CursorAuthError,
    api_error=cursor_client.CursorApiError,
    account_settings=True,
    control_total_label="Cursor current-cycle usage",
    seat_costs=True,
    live_cycle_total=True,
)
