"""Getting-started routes: the setup card state, dismissing it and resetting the data."""

from fastapi import APIRouter, Request

from costura import audit, scheduler, setup_state
from costura.api import schemas
from costura.api.deps import (
    OperatorOrgDep,
    OptionalUserDep,
    OrgDep,
    OwnedOrgDep,
    SessionDep,
    SettingsDep,
)
from costura.api.guard import VerifiedWriteDep, can_write
from costura.api.presenters.common import setup_out
from costura.orgs import reset_organization
from costura.spend.membership import membership

router = APIRouter()


@router.get("/orgs/{org}/setup", response_model=schemas.SetupOut)
def setup(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    org: OrgDep,
    user: OptionalUserDep,
) -> schemas.SetupOut:
    """Connection state, live runs and newest data. A member's read also requeues runs whose
    worker lease has expired (and fails them once attempts are spent). The anonymous read of
    the sample organization has no side effect."""
    if user is not None and membership(session, org.id, user.id) is not None:
        scheduler.recover_abandoned_runs_if_unlocked(session, org.id)
    return setup_out(session, settings, org, writes_enabled=can_write(request, session))


@router.post("/orgs/{org}/setup/dismiss", response_model=schemas.SetupOut)
def dismiss_setup(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    org: OperatorOrgDep,
    _guard: VerifiedWriteDep,
) -> schemas.SetupOut:
    """Hide the getting-started card for good; a second call keeps the first timestamp."""
    setup_state.dismiss(session, org)
    return setup_out(session, settings, org, writes_enabled=can_write(request, session))


@router.post("/orgs/{org}/setup/reset", response_model=schemas.SetupOut)
def reset_setup(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    org: OwnedOrgDep,
    _guard: VerifiedWriteDep,
) -> schemas.SetupOut:
    """Start over as if no key had ever been stored: delete the organization's credentials,
    every synced and derived row (`orgs.RESET_TABLES`) and the card dismissal, in one
    transaction; other organizations are untouched. The answer is the fresh setup state,
    `connect` unless a provider key comes from the environment (ANTHROPIC_ADMIN_KEY,
    OPENROUTER_ADMIN_KEY): that key cannot be deleted here, so the state is then `syncing`."""
    reset_organization(session, org.id)
    audit.record("organization_reset", session=session, org_id=org.id)
    return setup_out(session, settings, org, writes_enabled=can_write(request, session))
