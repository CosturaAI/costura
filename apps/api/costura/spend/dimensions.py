"""How a spend line becomes a row: the group key per dimension, its label, and the sentinel keys
for lines a dimension cannot name (no model, default workspace, unknown creator, Claude Code
logins, unallocated money).

`person` folds identities under one e-mail across providers; the other
principal dimensions stay provider-scoped."""

from costura.providers.registry import find_spec, get_spec, provider_origin
from costura.spend.inventory import (
    DIRECT_USER_LABEL,
    PLAYGROUND_LABEL,
    UNKNOWN_CREATOR_LABEL,
    InventoryResolver,
)
from costura.spend.taxonomy import (
    MODEL_DIMENSIONS,
    TAXONOMY_DIMENSIONS,
    resolve,
)

GroupKey = tuple[str, str]

UNALLOCATED_KEY = "__unallocated__"

UNALLOCATED_LABEL = "(unallocated cost)"

# Sentinel keys for rows that have no natural id in a dimension. The `__` prefix keeps them apart
# from provider ids, which never start with an underscore.
KEY_PLAYGROUND = "__playground__"

KEY_OAUTH = "__oauth__"

KEY_API_KEY_REQUEST = "__api_key_request__"

KEY_DEFAULT_WORKSPACE = "__default_workspace__"

KEY_UNKNOWN_CREATOR = "__unknown_creator__"

KEY_NO_MODEL = "__no_model__"

# First element of a group key whose row is one person across providers (the second element
# is the lowercased e-mail). Not a provider name, so labels never take a provider suffix.
PERSON_SCOPE = "__person__"

# First element of a group key whose row is one team across providers (the second element is
# the team slug, or `KEY_NO_TEAM` for spend no mapping reaches).
TEAM_SCOPE = "__team__"

KEY_NO_TEAM = "__no_team__"

NO_TEAM_LABEL = "(no team)"

# Dimensions whose rows name a principal; unallocated money is one sentinel row for them.
PRINCIPAL_DIMENSIONS = ("api_key", "account", "creator", "person", "team")

# Applied in Python after the SQL read. `origin` is a pure function of the provider slug, so
# `line_where` pushes it into the query. `person`, `creator` and `provider_account` have SQL
# forms for `is` / `one_of`, but the Python path also matches labels and `contains`. Model
# taxonomy and token type stay here: they come from the catalog regex and from unpivoted token
# columns.
PYTHON_FILTER_DIMENSIONS = (
    "person",
    "creator",
    "provider_account",
    *TAXONOMY_DIMENSIONS,
)


def account_of_person(
    resolver: InventoryResolver,
    provider: str,
    api_key_id: str | None,
    account_id: str | None,
) -> str | None:
    """Claude Code key owner for personal keys; provider account for direct login usage."""
    if api_key_id is None:
        return account_id
    return resolver.personal_key_owner(provider, api_key_id)


def line_person(
    resolver: InventoryResolver,
    provider: str,
    api_key_id: str | None,
    account_id: str | None,
) -> str | None:
    """The e-mail a line counts under in the `person` dimension; None for service keys,
    service accounts and ids outside the inventory."""
    if api_key_id is None:
        return resolver.person_of(provider, account_id)
    return resolver.key_person(provider, api_key_id)


def group_key(
    resolver: InventoryResolver,
    dimension: str,
    provider: str,
    api_key_id: str | None,
    account_id: str | None,
    workspace_id: str | None,
    model: str | None,
    provider_account_id: int | str | None = None,
) -> GroupKey:
    if dimension == "provider":
        return (provider, provider)
    if dimension == "origin":
        return (provider, provider_origin(provider))
    if dimension == "provider_account":
        return (provider, str(provider_account_id) if provider_account_id is not None else "0")
    if dimension == "api_key":
        if api_key_id is not None:
            return (provider, api_key_id)
        return (provider, KEY_OAUTH if account_id is not None else KEY_PLAYGROUND)
    if dimension == "account":
        return (provider, account_id if account_id is not None else KEY_API_KEY_REQUEST)
    if dimension == "person":
        return _person_key(resolver, provider, api_key_id, account_id)
    if dimension == "team":
        scope, person = _person_key(resolver, provider, api_key_id, account_id)
        team = resolver.team_of(
            provider, api_key_id, person if scope == PERSON_SCOPE else None, workspace_id
        )
        return (TEAM_SCOPE, team or KEY_NO_TEAM)
    if dimension == "creator":
        return (provider, _creator(resolver, provider, api_key_id, account_id))
    if dimension == "workspace":
        return (provider, workspace_id if workspace_id is not None else KEY_DEFAULT_WORKSPACE)
    if dimension in MODEL_DIMENSIONS:
        return (
            provider,
            resolve(provider, model).value(dimension),
        )
    return (provider, model if model is not None else KEY_NO_MODEL)


def _person_key(
    resolver: InventoryResolver, provider: str, api_key_id: str | None, account_id: str | None
) -> GroupKey:
    marked = resolver.marked_person(provider, api_key_id)
    if marked is not None:
        return (PERSON_SCOPE, marked)
    person_account_id = account_of_person(resolver, provider, api_key_id, account_id)
    email = resolver.person_of(provider, person_account_id)
    if email is not None:
        return (PERSON_SCOPE, email)
    return (provider, person_account_id if person_account_id is not None else KEY_API_KEY_REQUEST)


def _creator(
    resolver: InventoryResolver, provider: str, api_key_id: str | None, account_id: str | None
) -> str:
    if api_key_id is None:
        # OAuth usage is the account's own; playground has nobody.
        return account_id if account_id is not None else KEY_UNKNOWN_CREATOR
    return resolver.creator_of(provider, api_key_id) or KEY_UNKNOWN_CREATOR


def group_label(resolver: InventoryResolver, dimension: str, identity: GroupKey) -> str:
    provider, key = identity
    fixed = {
        UNALLOCATED_KEY: UNALLOCATED_LABEL,
        KEY_PLAYGROUND: PLAYGROUND_LABEL,
        KEY_API_KEY_REQUEST: resolver.account_label(provider, None),
        KEY_DEFAULT_WORKSPACE: resolver.workspace_label(provider, None),
        KEY_UNKNOWN_CREATOR: UNKNOWN_CREATOR_LABEL,
        KEY_NO_MODEL: "(none)",
        KEY_NO_TEAM: NO_TEAM_LABEL,
    }
    if key == KEY_OAUTH:
        spec = find_spec(provider)
        return (spec.login_usage_label if spec else None) or DIRECT_USER_LABEL
    if key in fixed:
        return fixed[key]
    if dimension == "api_key":
        return resolver.api_key_label(provider, key)
    if dimension == "team":
        return resolver.team_label(key)
    if dimension == "person" and provider == PERSON_SCOPE:
        return key
    if dimension in ("account", "creator", "person"):
        return resolver.user_email(provider, key)
    if dimension == "workspace":
        return resolver.workspace_label(provider, key)
    if dimension == "provider":
        return get_spec(key).label
    if dimension == "origin":
        return key
    if dimension == "provider_account":
        return resolver.provider_account_label(int(key)) or get_spec(provider).label
    return key


def group_details(
    resolver: InventoryResolver, dimension: str, identity: GroupKey
) -> dict[str, str]:
    provider, key = identity
    if dimension == "workspace" and key == KEY_DEFAULT_WORKSPACE:
        return {"admins": ""}
    if key.startswith("__"):
        return {}
    if dimension == "api_key":
        info = resolver.api_key(provider, key)
        if info is None:
            return {}
        return {
            "hint": info.partial_key_hint or "",
            "workspace": resolver.workspace_label(provider, info.workspace_external_id),
            "created_by": resolver.user_email(provider, info.created_by_external_id),
            "status": info.status + (" [missing]" if info.missing else ""),
        }
    if dimension == "workspace":
        return {"admins": ", ".join(resolver.workspace_admins(provider, key))}
    if dimension == "person":
        if provider == PERSON_SCOPE:
            return {"kind": "person"}
        return {"kind": resolver.user_kind(provider, key) or "unknown"}
    return {}


def group_person(resolver: InventoryResolver, dimension: str, identity: GroupKey) -> str | None:
    provider, key = identity
    if provider == PERSON_SCOPE:
        return key
    if key.startswith("__") or dimension not in ("account", "creator", "person"):
        return None
    return resolver.person_of(provider, key)
