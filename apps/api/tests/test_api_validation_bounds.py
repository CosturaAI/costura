"""Inputs past what the database stores answer 422, not 500."""

import pytest
from pydantic import BaseModel, ValidationError

from costura.api.schemas.anomalies import AlertReadIn
from costura.api.schemas.budgets import BudgetIn, InvoiceIn, OwnerAssignmentIn


@pytest.mark.parametrize(
    ("model", "valid", "oversized"),
    [
        (BudgetIn, {"amount": "999999999999"}, {"amount": "1e13"}),
        (InvoiceIn, {"amount": "10"}, {"amount": "1e13"}),
        (OwnerAssignmentIn, {"email": "a@b.example", "note": "x" * 500}, {"note": "x" * 501}),
        (AlertReadIn, {"anomaly_ids": list(range(500))}, {"anomaly_ids": list(range(501))}),
    ],
)
def test_oversized_inputs_are_refused(
    model: type[BaseModel], valid: dict[str, object], oversized: dict[str, object]
) -> None:
    model.model_validate(valid)
    with pytest.raises(ValidationError):
        model.model_validate(valid | oversized)
