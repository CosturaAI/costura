"""Provider inventory (API keys, workspaces, users) and the sync run history."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from costura.api import schemas
from costura.api.deps import (
    OrgDep,
    ProviderDep,
    SessionDep,
)
from costura.api.presenters.common import run_out
from costura.api.presenters.inventory import api_key_out, search_out, user_out, workspace_out
from costura.models import ProviderApiKey, ProviderUser, ProviderWorkspace
from costura.spend import inventory_lists
from costura.spend.inventory import (
    SEARCH_LIMIT_DEFAULT,
    SEARCH_LIMIT_MAX,
    InventoryResolver,
    search_inventory,
)
from costura.spend.inventory_lists import LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX
from costura.spend.posture import PostureReader

router = APIRouter()

LimitQuery = Annotated[int, Query(gt=0, le=LIST_LIMIT_MAX)]
OffsetQuery = Annotated[int, Query(ge=0)]
AccountQuery = Annotated[int | None, Query()]


@router.get(
    "/orgs/{org}/providers/{provider}/inventory/search",
    response_model=schemas.InventorySearchOut,
)
def inventory_search(
    session: SessionDep,
    org: OrgDep,
    provider: ProviderDep,
    q: Annotated[str, Query(min_length=2, max_length=100, pattern=r"\S.*\S|\S\S")],
    limit: Annotated[int, Query(gt=0, le=SEARCH_LIMIT_MAX)] = SEARCH_LIMIT_DEFAULT,
) -> schemas.InventorySearchOut:
    """Current keys, workspaces, people and services matching `q` in this scope.

    `q` is a literal substring of at least two characters. Each kind returns at most
    `limit` rows, ranked exact, then prefix, then substring. Missing rows are excluded.
    """
    return search_out(search_inventory(session, org.id, provider, q, limit))


@router.get("/orgs/{org}/providers/{provider}/runs", response_model=schemas.RunsOut)
def runs(
    session: SessionDep,
    org: OrgDep,
    provider: ProviderDep,
    limit: Annotated[int, Query(gt=0, le=500)] = 50,
    endpoint: Annotated[str | None, Query()] = None,
) -> schemas.RunsOut:
    rows = inventory_lists.sync_runs(session, org.id, provider, limit=limit, endpoint=endpoint)
    return schemas.RunsOut(runs=[run_out(session, run) for run in rows], as_of=datetime.now(UTC))


@router.get(
    "/orgs/{org}/providers/{provider}/inventory/api-keys", response_model=schemas.ApiKeysOut
)
def inventory_api_keys(
    session: SessionDep,
    org: OrgDep,
    provider: ProviderDep,
    include_missing: Annotated[bool, Query()] = True,
    limit: LimitQuery = LIST_LIMIT_DEFAULT,
    offset: OffsetQuery = 0,
) -> schemas.ApiKeysOut:
    """Keys by name. `total` counts every matching key; `limit` (at most 2000) and `offset`
    page through them."""
    page = inventory_lists.api_keys(
        session, org.id, provider, include_missing=include_missing, limit=limit, offset=offset
    )
    resolver = InventoryResolver(session, org.id, provider)
    posture = PostureReader(session, org.id, resolver, page.rows)
    return schemas.ApiKeysOut(
        items=[api_key_out(resolver, k, posture) for k in page.rows],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/orgs/{org}/providers/{provider}/inventory/api-keys/{external_id}",
    response_model=schemas.ApiKeyOut,
)
def inventory_api_key(
    session: SessionDep,
    org: OrgDep,
    provider: ProviderDep,
    external_id: str,
    account: AccountQuery = None,
) -> schemas.ApiKeyOut:
    """One key by provider id, missing or not; 404 when the inventory never saw it.

    `account` picks one provider account when the same external id exists on two consoles.
    """
    row = inventory_lists.inventory_row(
        session, ProviderApiKey, org.id, provider, external_id, account, "api key not found"
    )
    resolver = InventoryResolver(session, org.id, provider)
    return api_key_out(resolver, row, PostureReader(session, org.id, resolver, [row]))


@router.get(
    "/orgs/{org}/providers/{provider}/inventory/workspaces",
    response_model=schemas.WorkspacesOut,
)
def inventory_workspaces(
    session: SessionDep,
    org: OrgDep,
    provider: ProviderDep,
    include_missing: Annotated[bool, Query()] = True,
    limit: LimitQuery = LIST_LIMIT_DEFAULT,
    offset: OffsetQuery = 0,
) -> schemas.WorkspacesOut:
    """Workspaces by name, paged like the key list."""
    page = inventory_lists.workspaces(
        session, org.id, provider, include_missing=include_missing, limit=limit, offset=offset
    )
    resolver = InventoryResolver(session, org.id, provider)
    key_counts = inventory_lists.active_key_counts(session, org.id, provider)
    return schemas.WorkspacesOut(
        items=[workspace_out(resolver, w, key_counts) for w in page.rows],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/orgs/{org}/providers/{provider}/inventory/workspaces/{external_id}",
    response_model=schemas.WorkspaceOut,
)
def inventory_workspace(
    session: SessionDep,
    org: OrgDep,
    provider: ProviderDep,
    external_id: str,
    account: AccountQuery = None,
) -> schemas.WorkspaceOut:
    """One workspace by provider id. `account` selects among ids reused by two consoles."""
    row = inventory_lists.inventory_row(
        session, ProviderWorkspace, org.id, provider, external_id, account, "workspace not found"
    )
    resolver = InventoryResolver(session, org.id, provider)
    key_counts = inventory_lists.active_key_counts(session, org.id, provider)
    return workspace_out(resolver, row, key_counts)


@router.get("/orgs/{org}/providers/{provider}/inventory/users", response_model=schemas.UsersOut)
def inventory_users(
    session: SessionDep,
    org: OrgDep,
    provider: ProviderDep,
    include_missing: Annotated[bool, Query()] = True,
    limit: LimitQuery = LIST_LIMIT_DEFAULT,
    offset: OffsetQuery = 0,
) -> schemas.UsersOut:
    """Users and service accounts by e-mail, paged like the key list."""
    page = inventory_lists.users(
        session, org.id, provider, include_missing=include_missing, limit=limit, offset=offset
    )
    return schemas.UsersOut(
        items=[user_out(u) for u in page.rows],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/orgs/{org}/providers/{provider}/inventory/users/{external_id}",
    response_model=schemas.UserOut,
)
def inventory_user(
    session: SessionDep,
    org: OrgDep,
    provider: ProviderDep,
    external_id: str,
    account: AccountQuery = None,
) -> schemas.UserOut:
    """One user or service account. `account` selects among ids reused by two consoles."""
    row = inventory_lists.inventory_row(
        session, ProviderUser, org.id, provider, external_id, account, "user not found"
    )
    return user_out(row)
