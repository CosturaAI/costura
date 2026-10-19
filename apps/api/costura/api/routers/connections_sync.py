"""On-demand sync routes. The request only queues; the worker runs the syncs."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from costura import accounts, credentials
from costura.api import schemas
from costura.api.deps import OperatorOrgDep, ProviderDep, SessionDep, SettingsDep
from costura.api.guard import VerifiedWriteDep
from costura.connections import enqueue_syncs as _enqueue_syncs
from costura.providers.registry import ALL, provider_names

router = APIRouter()


@router.post(
    "/orgs/{org}/providers/{provider}/sync",
    response_model=schemas.SyncResultsOut,
    status_code=202,
)
def sync_now(
    session: SessionDep,
    settings: SettingsDep,
    org: OperatorOrgDep,
    provider: ProviderDep,
    _guard: VerifiedWriteDep,
    account: Annotated[int | None, Query()] = None,
) -> schemas.SyncResultsOut:
    """Queue every sync step for the current and previous month and answer 202 with one
    queued scheduler run per connected account. The worker runs them; the steps land on the
    row as they finish (`GET /orgs/{org}/setup`). Under `all` every connected provider gets
    its runs; 400 when none is connected. `?account=` queues one account of a concrete
    provider."""
    account_ids = None
    if provider == ALL:
        targets = [
            name
            for name in provider_names()
            if credentials.provider_connected(session, settings, org.id, name)
        ]
        if not targets:
            raise HTTPException(status_code=400, detail="no provider is connected")
    else:
        targets = [provider]
        if account is not None:
            accounts.get_account(session, org.id, provider, account)
            account_ids = {provider: [account]}
    runs = _enqueue_syncs(session, org.id, targets, trigger="api", account_ids=account_ids)
    results = [
        schemas.SyncResultOut(
            provider=run.provider,
            provider_account_id=run.provider_account_id,
            run_id=run.id,
            status=run.status,
            error=None,
            steps=[],
        )
        for run in runs
    ]
    return schemas.SyncResultsOut(results=results)
