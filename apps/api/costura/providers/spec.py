"""The contract a connector fulfils: one `ProviderSpec` names its credentials, sync steps,
reconcile readers and errors. Each provider package builds its own spec in `spec.py`;
`costura.providers.registry` only collects them."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol, Self

from pydantic import SecretStr
from sqlalchemy.orm import Session

from costura.config import Settings
from costura.providers.runs import InventorySummary, SyncSummary, Target

Attribution = Literal["token_share", "direct", "key_attributed"]

ConnectionType = Literal["provider_api"]


class ProviderClient(Protocol):
    """What the sync cycle needs from any provider client: a context that closes it."""

    def __enter__(self) -> Self: ...

    def __exit__(self, *_args: object) -> None: ...

    def close(self) -> None: ...


# (session, target, client, window_start, window_end) -> summary
SyncStep = Callable[[Session, Target, Any, datetime, datetime], SyncSummary]

# (raw page payload, window_start, window_end) -> amount per api_key_id (None: no key)
KeyAmounts = Callable[[dict[str, Any], datetime, datetime], dict[str | None, Decimal]]

PageAmountWithParams = Callable[[dict[str, Any], dict[str, Any], datetime, datetime], Decimal]


class NotManagementKey(ValueError):
    """The key authenticates but is not a management key; the analytics routes would 403."""


@dataclass(frozen=True)
class AccountInfo:
    """What a provider tells about the account a key opens, read once when it is connected:
    the provider's own id of the account and the name it shows."""

    external_id: str | None
    name: str | None


# (client) -> what the provider reports about the account; None when it reports nothing.
AccountInfoReader = Callable[[Any], AccountInfo | None]


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    label: str
    vendor: str
    surface: str
    key_label: str
    key_prefix: str
    console_label: str
    console_url: str
    env_var: str
    env_secret: Callable[[Settings], SecretStr | None]
    base_url_of: Callable[[Settings], str]
    attribution: Attribution
    cost_endpoint: str
    total_endpoint: str
    sync_steps: tuple[tuple[str, SyncStep], ...]
    # Step names whose success `allocate` waits for: a provider that prices per key needs only
    # `cost`; one that reports money and tokens apart needs both.
    allocation_inputs: tuple[str, ...]
    # Endpoints whose runs rewrite the day's amounts (the anomaly evidence reads them to tell
    # when a figure changed after detection); control totals touch no line and stay out.
    data_endpoints: tuple[str, ...]
    client_factory: Callable[[Settings, str, str | None], ProviderClient]
    validate: Callable[[Any], None]
    run_inventory_sync: Callable[[Session, Target, Any], list[InventorySummary]]
    page_amount: Callable[[dict[str, Any], datetime, datetime], Decimal]
    auth_error: type[Exception]
    api_error: type[Exception]
    page_amount_with_params: PageAmountWithParams | None = None
    # Providers that publish their own per-key money store it as raw pages under
    # `key_endpoint`; `key_amounts(payload, start, end)` sums one page per `api_key_id` so
    # Reconcile can set the provider's figure beside the token-share allocation.
    key_endpoint: str | None = None
    key_amounts: KeyAmounts | None = None
    # Labels a new account from the provider's own record of it; None where none is offered.
    account_info: AccountInfoReader | None = None
    connection_type: ConnectionType = "provider_api"
    env_account_id: Callable[[Settings], str | None] | None = None
    # Capabilities the routers branch on. A provider that needs one sets it; the routers read
    # the flag instead of comparing the provider name.
    requires_workspace: bool = False
    keys_console_url: str | None = None
    account_settings: bool = False
    setup_pricing: bool = False
    control_total_label: str | None = None
    # Usage families synced under `usage_<family>`; Reconcile reports which ones covered the
    # window. Empty where the provider reports activity in one endpoint.
    activity_families: tuple[str, ...] = ()
    # Usage lines carry the provider's own per-user money, so Reconcile compares Costura's
    # total with the user-attributed one and reports the data watermark.
    user_attributed: bool = False
    # Days of history the provider's report API serves; a month that starts before it is
    # skipped rather than failed. None where no limit is documented.
    history_days: int | None = None
    # Cost lines name a seat pool in `description`; allocation splits each pool across the
    # users of that pool instead of copying per-user amounts.
    pooled_seats: bool = False
    # Seat charges are derived in Costura and left out of the provider's control total.
    seat_costs: bool = False
    # The current billing cycle's total comes from the latest live total run, not the stored
    # control total of the window.
    live_cycle_total: bool = False
    # Usage is billed in credits priced per account; Reconcile checks the credit pricing.
    credit_pricing: bool = False
    # A GitHub login maps to an e-mail by a table the operator maintains on the account.
    login_mapping: bool = False
    # Keys the provider creates for one person's coding-agent session count as that person's.
    personal_session_keys: bool = False
    # Label of usage made through a login rather than a key; None uses the generic label.
    login_usage_label: str | None = None
    # Not yet run against a live organization; the API and the web report it.
    experimental: bool = False

    def env_key(self, settings: Settings) -> str | None:
        secret = self.env_secret(settings)
        return None if secret is None else secret.get_secret_value()

    def base_url(self, settings: Settings) -> str:
        return self.base_url_of(settings)

    def env_account(self, settings: Settings) -> str | None:
        return None if self.env_account_id is None else self.env_account_id(settings)
