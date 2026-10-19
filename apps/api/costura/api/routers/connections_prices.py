"""Credit price routes: one account prices its own credits."""

from fastapi import APIRouter, Response

from costura import credit_prices
from costura.api import schemas
from costura.api.deps import CurrentUserDep, OperatorOrgDep, OrgDep, SessionDep
from costura.api.guard import VerifiedWriteDep

router = APIRouter()


def _credit_price_out(row: credit_prices.CreditPrice) -> schemas.CreditPriceOut:
    return schemas.CreditPriceOut(
        id=row.id,
        organization_id=row.organization_id,
        provider_account_id=row.provider_account_id,
        effective_from=row.effective_from,
        price_per_credit=schemas.money_exact(row.price_per_credit) or "0.00000000",
        created_by=row.created_by,
        created_at=row.created_at,
    )


@router.get(
    "/orgs/{org}/accounts/{account_id}/credit-prices",
    response_model=list[schemas.CreditPriceOut],
)
def list_credit_prices(
    session: SessionDep, org: OrgDep, account_id: int
) -> list[schemas.CreditPriceOut]:
    rows = credit_prices.list_prices(session, org.id, account_id)
    return [_credit_price_out(row) for row in rows]


@router.post(
    "/orgs/{org}/accounts/{account_id}/credit-prices",
    response_model=schemas.CreditPriceOut,
    status_code=201,
)
def add_credit_price(
    session: SessionDep,
    org: OperatorOrgDep,
    user: CurrentUserDep,
    account_id: int,
    body: schemas.CreditPriceIn,
    _guard: VerifiedWriteDep,
) -> schemas.CreditPriceOut:
    row = credit_prices.create_price(
        session,
        org.id,
        account_id,
        effective_from=body.effective_from,
        price_per_credit=body.price_per_credit,
        created_by=user.id,
    )
    session.flush()
    return _credit_price_out(row)


@router.delete(
    "/orgs/{org}/accounts/{account_id}/credit-prices/{price_id}",
    status_code=204,
)
def remove_credit_price(
    session: SessionDep,
    org: OperatorOrgDep,
    account_id: int,
    price_id: int,
    _guard: VerifiedWriteDep,
) -> Response:
    credit_prices.delete_price(session, org.id, account_id, price_id)
    session.flush()
    return Response(status_code=204)
