"""Two accounts that report the same provider organization are flagged."""

from sqlalchemy.orm import Session

from costura.models import ProviderAccount, ProviderApiKey
from costura.spend.duplicates import duplicate_accounts
from tests.conftest import ORG_ID, account_of
from tests.seed import sync_run


def _keys(session: Session, account: int, ids: list[str]) -> None:
    from datetime import UTC, datetime

    today = datetime.now(UTC).date()
    run = sync_run(session, ORG_ID, "openai", "api_keys", today, today)
    for external_id in ids:
        session.add(
            ProviderApiKey(
                organization_id=ORG_ID,
                provider="openai",
                provider_account_id=account,
                sync_run_id=run.id,
                external_id=external_id,
                name=external_id,
                status="active",
            )
        )
    session.flush()


def test_overlapping_inventories_are_one_organization(db_session: Session) -> None:
    first = account_of(db_session, ORG_ID, "openai")
    second = ProviderAccount(organization_id=ORG_ID, provider="openai", label="Rotated")
    db_session.add(second)
    db_session.flush()
    _keys(db_session, first, ["k1", "k2", "k3", "k4"])
    _keys(db_session, second.id, ["k1", "k2"])
    assert duplicate_accounts(db_session, ORG_ID, "all") == []

    _keys(db_session, second.id, ["k3"])
    [pair] = duplicate_accounts(db_session, ORG_ID, "openai")
    assert (pair.first.id, pair.second.id, pair.shared) == (first, second.id, 3)

    second.disconnected_at = second.created_at
    db_session.flush()
    assert duplicate_accounts(db_session, ORG_ID, "openai") == []
