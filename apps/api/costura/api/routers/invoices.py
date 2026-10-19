"""Invoice totals typed in per provider account and month, read by reconciliation."""

from typing import Annotated

from fastapi import APIRouter, Path, Response

from costura import audit
from costura.api import schemas
from costura.api.deps import (
    ConcreteProviderDep,
    CurrentUserDep,
    OrgDep,
    OwnedOrgDep,
    SessionDep,
)
from costura.api.guard import VerifiedWriteDep
from costura.api.presenters.spend import invoice_out
from costura.spend import invoices

router = APIRouter()

MonthPath = Annotated[str, Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


@router.get(
    "/orgs/{org}/providers/{provider}/months/{month}/invoices",
    response_model=schemas.InvoicesOut,
)
def list_invoices(
    session: SessionDep, org: OrgDep, provider: ConcreteProviderDep, month: MonthPath
) -> schemas.InvoicesOut:
    """The invoice totals typed in for the month, one per provider account that has one."""
    views = invoices.month_invoice_views(session, org.id, provider, month)
    return schemas.InvoicesOut(month=month, items=[invoice_out(view) for view in views])


@router.put(
    "/orgs/{org}/providers/{provider}/accounts/{account_id}/invoices/{month}",
    response_model=schemas.InvoiceOut,
)
def set_invoice(
    session: SessionDep,
    org: OwnedOrgDep,
    provider: ConcreteProviderDep,
    account_id: int,
    month: MonthPath,
    body: schemas.InvoiceIn,
    user: CurrentUserDep,
    _guard: VerifiedWriteDep,
) -> schemas.InvoiceOut:
    """Record what the provider invoiced one account for one month, tax and credits as the
    bill shows them. Owner only: it is the figure finance reconciles against. 422 on a
    malformed month or a negative amount; 404 on an account of another provider."""
    view = invoices.set_invoice(
        session,
        org.id,
        provider,
        account_id,
        month,
        amount=body.amount,
        note=body.note,
        user_id=user.id,
    )
    audit.record("invoice_set", session=session, org_id=org.id, provider=provider, user_id=user.id)
    return invoice_out(view)


@router.delete(
    "/orgs/{org}/providers/{provider}/accounts/{account_id}/invoices/{month}",
    status_code=204,
)
def delete_invoice(
    session: SessionDep,
    org: OwnedOrgDep,
    provider: ConcreteProviderDep,
    account_id: int,
    month: MonthPath,
    user: CurrentUserDep,
    _guard: VerifiedWriteDep,
) -> Response:
    invoices.delete_invoice(session, org.id, provider, account_id, month)
    audit.record(
        "invoice_removed", session=session, org_id=org.id, provider=provider, user_id=user.id
    )
    return Response(status_code=204)
