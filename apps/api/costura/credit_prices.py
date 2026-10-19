"""Codex credit price schedules scoped to one provider account."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.errors import DomainError
from costura.models.account import ProviderAccount
from costura.models.credit_price import CreditPrice
from costura.providers.codex import PROVIDER as CODEX
from costura.spend.window import shift_month

HORIZON_MONTHS = 13


class UnknownCreditPrice(LookupError, DomainError):
    status = 404
    code = "unknown_credit_price"

    pass


class UnknownCreditAccount(LookupError, DomainError):
    status = 404
    code = "unknown_credit_account"

    pass


class InvalidCreditAccount(ValueError, DomainError):
    status = 422
    code = "invalid_credit_account"

    pass


class DuplicateEffectiveDate(ValueError, DomainError):
    status = 422
    code = "duplicate_effective_date"

    pass


class InvalidCreditPrice(ValueError, DomainError):
    status = 422
    code = "invalid_credit_price"

    pass


class EffectiveDateOutOfRange(ValueError, DomainError):
    status = 422
    code = "effective_date_out_of_range"

    pass


def _shift_months(value: date, months: int) -> date:

    return shift_month(value, months)


def date_horizon(today: date | None = None) -> tuple[date, date]:
    today = today or datetime.now(UTC).date()
    return _shift_months(today, -HORIZON_MONTHS), _shift_months(today, HORIZON_MONTHS)


def codex_account(session: Session, organization_id: int, account_id: int) -> ProviderAccount:
    account = session.get(ProviderAccount, account_id)
    if account is None or account.organization_id != organization_id:
        raise UnknownCreditAccount(f"no account {account_id} in this organization")
    if account.provider != CODEX:
        raise InvalidCreditAccount("credit prices apply only to Codex accounts")
    return account


def list_prices(session: Session, organization_id: int, account_id: int) -> list[CreditPrice]:
    codex_account(session, organization_id, account_id)
    return list(
        session.scalars(
            select(CreditPrice)
            .where(
                CreditPrice.organization_id == organization_id,
                CreditPrice.provider_account_id == account_id,
            )
            .order_by(CreditPrice.effective_from, CreditPrice.id)
        ).all()
    )


def create_price(
    session: Session,
    organization_id: int,
    account_id: int,
    *,
    effective_from: date,
    price_per_credit: Decimal,
    created_by: int | None,
    today: date | None = None,
) -> CreditPrice:
    codex_account(session, organization_id, account_id)
    if not price_per_credit.is_finite() or price_per_credit <= 0:
        raise InvalidCreditPrice("price_per_credit must be a positive finite amount")
    earliest, latest = date_horizon(today)
    if not earliest <= effective_from <= latest:
        raise EffectiveDateOutOfRange(
            f"effective_from must be between {earliest.isoformat()} and {latest.isoformat()}"
        )
    duplicate = session.scalar(
        select(CreditPrice.id).where(
            CreditPrice.organization_id == organization_id,
            CreditPrice.provider_account_id == account_id,
            CreditPrice.effective_from == effective_from,
        )
    )
    if duplicate is not None:
        raise DuplicateEffectiveDate(
            f"a credit price already starts on {effective_from.isoformat()}"
        )
    row = CreditPrice(
        organization_id=organization_id,
        provider_account_id=account_id,
        effective_from=effective_from,
        price_per_credit=price_per_credit,
        created_by=created_by,
    )
    session.add(row)
    session.flush()
    return row


def delete_price(session: Session, organization_id: int, account_id: int, price_id: int) -> None:
    codex_account(session, organization_id, account_id)
    row = session.get(CreditPrice, price_id)
    if (
        row is None
        or row.organization_id != organization_id
        or row.provider_account_id != account_id
    ):
        raise UnknownCreditPrice(f"credit price {price_id} not found")
    session.delete(row)
    session.flush()


__all__ = [
    "HORIZON_MONTHS",
    "DuplicateEffectiveDate",
    "EffectiveDateOutOfRange",
    "InvalidCreditAccount",
    "InvalidCreditPrice",
    "UnknownCreditAccount",
    "UnknownCreditPrice",
    "codex_account",
    "create_price",
    "date_horizon",
    "delete_price",
    "list_prices",
]
