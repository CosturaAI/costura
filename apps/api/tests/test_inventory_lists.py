"""Paged inventory lists: the page holds at most `limit` rows and `total` counts them all."""

from datetime import date

from sqlalchemy.orm import Session

from costura.models import ProviderApiKey
from costura.spend import inventory_lists
from tests.conftest import ORG_ID, account_of
from tests.seed import sync_run


def _keys(session: Session, count: int) -> None:
    account = account_of(session, ORG_ID, "anthropic")
    run = sync_run(session, ORG_ID, "anthropic", "api_keys", date(2026, 9, 1), date(2026, 9, 2))
    for n in range(count):
        session.add(
            ProviderApiKey(
                organization_id=ORG_ID,
                provider="anthropic",
                provider_account_id=account,
                external_id=f"key_{n:02d}",
                name=f"key {n:02d}",
                status="active",
                sync_run_id=run.id,
            )
        )
    session.flush()


def test_api_key_pages_count_every_key_and_hold_at_most_limit(db_session: Session) -> None:
    _keys(db_session, 5)
    first = inventory_lists.api_keys(
        db_session, ORG_ID, "anthropic", include_missing=True, limit=2, offset=0
    )
    last = inventory_lists.api_keys(
        db_session, ORG_ID, "anthropic", include_missing=True, limit=2, offset=4
    )
    assert (first.total, [k.external_id for k in first.rows]) == (5, ["key_00", "key_01"])
    assert (last.total, [k.external_id for k in last.rows]) == (5, ["key_04"])
