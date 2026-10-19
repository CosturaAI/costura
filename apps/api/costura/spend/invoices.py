"""The invoice total reconciliation compares against, from the figures owners typed in.

One row per provider account and calendar month. A provider's month has an invoice total only
when every account with cost lines in that month has one; a partial sum would read as a
mismatch that is only missing input.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import accounts
from costura.errors import NotFound
from costura.models import ProviderInvoice, User
from costura.spend.ledger import has_cost_lines
from costura.spend.window import Window


def month_invoices(
    session: Session, org_id: int, provider: str, month: str
) -> dict[int, ProviderInvoice]:
    """Provider account id -> the invoice typed in for `month`."""
    rows = session.scalars(
        select(ProviderInvoice).where(
            ProviderInvoice.organization_id == org_id,
            ProviderInvoice.provider == provider,
            ProviderInvoice.month == month,
        )
    )
    return {row.provider_account_id: row for row in rows}


def invoice_total(
    session: Session,
    org_id: int,
    provider: str,
    month: str,
    account_ids: list[int],
    account_id: int | None = None,
) -> Decimal | None:
    """The invoiced amount for the month: one account's figure when `account_id` is given,
    otherwise the sum over `account_ids` with cost lines in the month. None when an account
    that spent has no invoice yet."""
    invoices = month_invoices(session, org_id, provider, month)
    if account_id is not None:
        row = invoices.get(account_id)
        return None if row is None else row.amount
    window = Window.for_month(month)
    spending = [
        account
        for account in account_ids
        if has_cost_lines(session, org_id, provider, window, account)
    ]
    if not spending or any(account not in invoices for account in spending):
        return None
    return sum((invoices[account].amount for account in spending), Decimal("0"))


@dataclass(frozen=True)
class InvoiceView:
    row: ProviderInvoice
    account_label: str
    entered_by: str | None


def _view(session: Session, row: ProviderInvoice, labels: dict[int, str]) -> InvoiceView:
    label = labels.get(row.provider_account_id)
    if label is None:
        label = accounts.get_account(
            session, row.organization_id, row.provider, row.provider_account_id
        ).label
    user = None if row.entered_by is None else session.get(User, row.entered_by)
    return InvoiceView(
        row=row, account_label=label, entered_by=None if user is None else user.email
    )


def month_invoice_views(
    session: Session, org_id: int, provider: str, month: str
) -> list[InvoiceView]:
    """The month's invoices in account order, with the labels and author the page shows."""
    rows = month_invoices(session, org_id, provider, month)
    labels = {a.id: a.label for a in accounts.list_accounts(session, org_id, provider)}
    return [_view(session, rows[account], labels) for account in sorted(rows)]


def set_invoice(
    session: Session,
    org_id: int,
    provider: str,
    account_id: int,
    month: str,
    *,
    amount: Decimal,
    note: str | None,
    user_id: int,
) -> InvoiceView:
    """Create or replace one account's invoice for the month. 404 on an account of another
    provider."""
    accounts.get_account(session, org_id, provider, account_id)
    row = session.get(ProviderInvoice, (org_id, provider, account_id, month))
    if row is None:
        row = ProviderInvoice(
            organization_id=org_id,
            provider=provider,
            provider_account_id=account_id,
            month=month,
        )
        session.add(row)
    row.amount = amount.quantize(Decimal("0.01"))
    row.note = (note or "").strip() or None
    row.entered_by = user_id
    session.flush()
    session.refresh(row)
    return _view(session, row, {})


def delete_invoice(
    session: Session, org_id: int, provider: str, account_id: int, month: str
) -> None:
    row = session.get(ProviderInvoice, (org_id, provider, account_id, month))
    if row is None:
        raise NotFound("no invoice for this account and month")
    session.delete(row)
    session.flush()
