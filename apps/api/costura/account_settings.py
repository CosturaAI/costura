"""Per-account settings a connector reads during sync: Cursor seat pricing and the Copilot
login table. Kept apart from `costura.accounts` so provider packages read them without
importing the provider registry."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from costura.models import ProviderAccount


@dataclass(frozen=True)
class CursorAccountSettings:
    seat_price_usd: Decimal
    include_included_in_business: bool
    effective_from: date


def cursor_settings(account: ProviderAccount) -> CursorAccountSettings:
    raw = account.settings or {}
    return CursorAccountSettings(
        seat_price_usd=Decimal(str(raw.get("seat_price_usd", 0))),
        include_included_in_business=raw.get("include_included_in_business", True) is True,
        effective_from=account.settings_effective_from,
    )


def copilot_logins(account: ProviderAccount) -> dict[str, str]:
    """Lowercased GitHub login -> e-mail, as an owner mapped them for a Copilot account."""
    raw = (account.settings or {}).get("logins")
    if not isinstance(raw, dict):
        return {}
    return {
        str(login).strip().lower(): str(email).strip().lower()
        for login, email in raw.items()
        if isinstance(email, str) and "@" in email and str(login).strip()
    }
