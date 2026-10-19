"""The credit price in force on a day, read from an account's schedule."""

from datetime import date
from decimal import Decimal

from costura.models.credit_price import CreditPrice


def effective_price(prices: list[CreditPrice], day: date) -> Decimal | None:
    selected = next(
        (row for row in reversed(prices) if row.effective_from <= day),
        None,
    )
    return None if selected is None else Decimal(selected.price_per_credit)
