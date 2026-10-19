"""Budgets, budget statuses, owner assignments and personal keys."""

from fastapi import APIRouter, HTTPException, Response

from costura import audit
from costura.api import schemas
from costura.api.deps import (
    ConcreteProviderDep,
    CurrentUserDep,
    OperatorOrgDep,
    OrgDep,
    OwnedOrgDep,
    ProviderDep,
    SessionDep,
    WindowDep,
)
from costura.api.guard import VerifiedWriteDep
from costura.api.presenters.budgets import (
    budget_out,
    budget_statuses_out,
    owner_assignment_out,
    personal_key_out,
)
from costura.identity_policy import require_email
from costura.models.budget import BudgetScopeKind
from costura.models.owner import OwnerAssignmentKind
from costura.spend import assignments, budgets
from costura.spend.inventory import InventoryResolver

router = APIRouter()

EMAIL_SHAPE = "email must look like you@example.com"


@router.get("/orgs/{org}/providers/{provider}/budgets", response_model=schemas.BudgetsOut)
def budgets_route(session: SessionDep, org: OrgDep, provider: ProviderDep) -> schemas.BudgetsOut:
    """Configured budgets: the organization total and any workspace, standing across months."""
    resolver = InventoryResolver(session, org.id, provider)
    return schemas.BudgetsOut(
        budgets=[budget_out(resolver, b) for b in budgets.list_budgets(session, org.id, provider)]
    )


@router.get(
    "/orgs/{org}/providers/{provider}/owners", response_model=list[schemas.OwnerAssignmentOut]
)
def list_owner_assignments(
    session: SessionDep, org: OrgDep, provider: ConcreteProviderDep
) -> list[schemas.OwnerAssignmentOut]:
    """The contacts assigned by hand to keys and workspaces of this provider."""
    resolver = InventoryResolver(session, org.id, provider)
    return [
        owner_assignment_out(resolver, view)
        for view in assignments.owner_assignments(session, org.id, provider)
    ]


@router.put(
    "/orgs/{org}/providers/{provider}/owners/{kind}/{external_id}",
    response_model=schemas.OwnerAssignmentOut,
)
def set_owner_assignment(
    session: SessionDep,
    org: OperatorOrgDep,
    provider: ConcreteProviderDep,
    kind: OwnerAssignmentKind,
    external_id: str,
    body: schemas.OwnerAssignmentIn,
    user: CurrentUserDep,
    _guard: VerifiedWriteDep,
) -> schemas.OwnerAssignmentOut:
    """Record who answers for a key or a workspace when the provider inventory names nobody
    (or the wrong person). Any member may assign; the anomaly pages read it before the
    inventory. 422 on an unknown kind or a malformed e-mail."""
    view = assignments.set_owner_assignment(
        session,
        org.id,
        provider,
        kind,
        external_id,
        email=require_email(body.email, EMAIL_SHAPE),
        note=body.note,
        user_id=user.id,
    )
    return owner_assignment_out(InventoryResolver(session, org.id, provider), view)


@router.delete("/orgs/{org}/providers/{provider}/owners/{kind}/{external_id}", status_code=204)
def delete_owner_assignment(
    session: SessionDep,
    org: OperatorOrgDep,
    provider: ConcreteProviderDep,
    kind: OwnerAssignmentKind,
    external_id: str,
    _guard: VerifiedWriteDep,
) -> Response:
    assignments.delete_owner_assignment(session, org.id, provider, kind, external_id)
    return Response(status_code=204)


@router.get(
    "/orgs/{org}/providers/{provider}/personal-keys",
    response_model=list[schemas.PersonalKeyOut],
)
def list_personal_keys(
    session: SessionDep, org: OrgDep, provider: ProviderDep
) -> list[schemas.PersonalKeyOut]:
    """The API keys a member marked as one person's own, on the providers in scope."""
    resolver = InventoryResolver(session, org.id, provider)
    return [
        personal_key_out(resolver, view)
        for view in assignments.personal_keys(session, org.id, provider)
    ]


@router.put(
    "/orgs/{org}/providers/{provider}/personal-keys/{api_key_id}",
    response_model=schemas.PersonalKeyOut,
)
def set_personal_key(
    session: SessionDep,
    org: OperatorOrgDep,
    provider: ConcreteProviderDep,
    api_key_id: str,
    body: schemas.PersonalKeyIn,
    user: CurrentUserDep,
    _guard: VerifiedWriteDep,
) -> schemas.PersonalKeyOut:
    """Count a key's spend under one person in the `person` dimension, ahead of the Claude
    Code key rule. The address must belong to a user in the organization's provider inventory,
    on any provider, so the person row and page exist; 422 otherwise. 404 when the key is not
    in the inventory."""
    resolver = InventoryResolver(session, org.id, provider)
    view = assignments.set_personal_key(
        session,
        org.id,
        provider,
        api_key_id,
        email=require_email(body.email, EMAIL_SHAPE),
        user_id=user.id,
        resolver=resolver,
    )
    audit.record(
        "personal_key_set", session=session, org_id=org.id, provider=provider, user_id=user.id
    )
    return personal_key_out(resolver, view)


@router.delete("/orgs/{org}/providers/{provider}/personal-keys/{api_key_id}", status_code=204)
def delete_personal_key(
    session: SessionDep,
    org: OperatorOrgDep,
    provider: ConcreteProviderDep,
    api_key_id: str,
    user: CurrentUserDep,
    _guard: VerifiedWriteDep,
) -> Response:
    assignments.delete_personal_key(session, org.id, provider, api_key_id)
    audit.record(
        "personal_key_removed", session=session, org_id=org.id, provider=provider, user_id=user.id
    )
    return Response(status_code=204)


@router.put(
    "/orgs/{org}/providers/{provider}/budgets/{scope_kind}/{scope_id}",
    response_model=schemas.BudgetOut,
)
def set_budget_route(
    session: SessionDep,
    org: OwnedOrgDep,
    provider: ProviderDep,
    scope_kind: BudgetScopeKind,
    scope_id: str,
    body: schemas.BudgetIn,
    _guard: VerifiedWriteDep,
) -> schemas.BudgetOut:
    """Create or replace the budget of one scope. A person budget (`person/<email>`) lives
    under provider `all` and sums that e-mail across every provider; the organization budget
    (`org/__org__`) under `all` sums every provider, its projection included; a workspace
    needs one provider (400 under `all`). `period` day or week compares each UTC day or ISO
    week with the amount; a person budget is monthly. 422 on an unknown scope kind, a
    non-positive amount, a threshold outside 1..200 or a day or week person budget; 404 when
    the workspace or the person is not in the inventory."""
    assignments.check_budget_scope(session, org.id, provider, scope_kind, scope_id)
    row = budgets.set_budget(
        session,
        org.id,
        provider,
        scope_kind,
        scope_id,
        body.amount,
        body.thresholds,
        period=body.period,
    )
    return budget_out(InventoryResolver(session, org.id, provider), row)


@router.delete("/orgs/{org}/providers/{provider}/budgets/{scope_kind}/{scope_id}", status_code=204)
def delete_budget_route(
    session: SessionDep,
    org: OwnedOrgDep,
    provider: ProviderDep,
    scope_kind: BudgetScopeKind,
    scope_id: str,
    _guard: VerifiedWriteDep,
) -> Response:
    """Remove the budget and every alert it raised."""
    assignments.require_budget_provider(provider, scope_kind)
    if scope_kind == "person":
        scope_id = scope_id.strip().lower()
    if not budgets.delete_budget(session, org.id, provider, scope_kind, scope_id):
        raise HTTPException(status_code=404, detail="budget not found")
    return Response(status_code=204)


@router.get(
    "/orgs/{org}/providers/{provider}/months/{month}/budgets",
    response_model=schemas.BudgetStatusesOut,
)
def budget_statuses_route(
    session: SessionDep, org: OrgDep, provider: ProviderDep, window: WindowDep, month: str
) -> schemas.BudgetStatusesOut:
    """Spend against every budget for the month, with the alerts the scheduler recorded.
    Spend and percentages are computed on read; alerts are the stored history."""
    statuses = budgets.budget_statuses(session, org.id, provider, window)
    return budget_statuses_out(InventoryResolver(session, org.id, provider), month, statuses)
