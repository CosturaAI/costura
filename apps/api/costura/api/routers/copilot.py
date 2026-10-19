"""The login-to-e-mail table of a GitHub Copilot account.

GitHub names a seat holder by login and returns no e-mail, so an owner records which e-mail
each login is. The next inventory sync rewrites the users with it; a login left out keeps
its public profile e-mail, or the login itself.
"""

from fastapi import APIRouter, HTTPException

from costura import accounts, audit
from costura.api import schemas
from costura.api.deps import (
    ConcreteProviderDep,
    CurrentUserDep,
    OrgDep,
    OwnedOrgDep,
    SessionDep,
)
from costura.api.guard import VerifiedWriteDep
from costura.providers.copilot import PROVIDER as COPILOT

router = APIRouter()


def _copilot_only(provider: str) -> None:
    if provider != COPILOT:
        raise HTTPException(status_code=404, detail="login mapping exists for GitHub Copilot only")


@router.get(
    "/orgs/{org}/providers/{provider}/accounts/{account_id}/logins",
    response_model=schemas.CopilotLoginsOut,
)
def list_logins(
    session: SessionDep, org: OrgDep, provider: ConcreteProviderDep, account_id: int
) -> schemas.CopilotLoginsOut:
    _copilot_only(provider)
    account = accounts.get_account(session, org.id, provider, account_id)
    return schemas.CopilotLoginsOut(account_id=account.id, logins=accounts.copilot_logins(account))


@router.put(
    "/orgs/{org}/providers/{provider}/accounts/{account_id}/logins",
    response_model=schemas.CopilotLoginsOut,
)
def set_logins(
    session: SessionDep,
    org: OwnedOrgDep,
    provider: ConcreteProviderDep,
    account_id: int,
    body: schemas.CopilotLoginsIn,
    user: CurrentUserDep,
    _guard: VerifiedWriteDep,
) -> schemas.CopilotLoginsOut:
    """Replace the whole table. 422 on an address that does not look like an e-mail."""
    _copilot_only(provider)
    account = accounts.get_account(session, org.id, provider, account_id)
    logins = accounts.set_copilot_logins(account, body.logins)
    session.flush()
    audit.record(
        "copilot_logins_set", session=session, org_id=org.id, user_id=user.id, count=len(logins)
    )
    return schemas.CopilotLoginsOut(account_id=account.id, logins=logins)
