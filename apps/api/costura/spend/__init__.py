"""Provider-independent spend arithmetic and reporting."""

from costura.spend.taxonomy import MODEL_DIMENSIONS, TOKEN_TYPE

# Dimensions the reconciliation breakdown accepts; resolved to columns in `spend.reconcile`.
BREAKDOWN_DIMENSIONS = (
    "day",
    "workspace",
    "model",
    "token_type",
    "cost_type",
    "service_tier",
    "description",
)

# Dimensions the usage breakdown accepts; resolved to columns in `spend.usage`. `provider`
# groups by the connector that produced the line and is meaningful under the `all` scope;
# `provider_account` by the console the line was synced from; `person` groups
# accounts by the e-mail the inventory knows them under, across providers.
USAGE_DIMENSIONS = (
    "api_key",
    "account",
    "creator",
    "workspace",
    "model",
    "provider",
    "origin",
    "provider_account",
    "person",
    "team",
    *MODEL_DIMENSIONS,
    TOKEN_TYPE,
    "cost_type",
)

# Dimensions the daily series (`GET .../series?by=`) accepts; `none` is one total per day.
SERIES_DIMENSIONS = (*USAGE_DIMENSIONS, "cost_type", "none")

# Query filters accepted by usage and series routes; each names a column on the line tables,
# except `person`, which expands to the `(provider, account_id)` identities of one e-mail, and
# `provider_account`, the id of one provider account.
FILTER_KEYS = (
    "api_key",
    "account",
    "creator",
    "workspace",
    "model",
    "provider",
    "origin",
    "provider_account",
    "person",
    *MODEL_DIMENSIONS,
    TOKEN_TYPE,
)

__all__ = [
    "BREAKDOWN_DIMENSIONS",
    "FILTER_KEYS",
    "SERIES_DIMENSIONS",
    "USAGE_DIMENSIONS",
]
