from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.api.presenters.inventory import api_key_out
from costura.models import ProviderApiKey, ProviderUser
from costura.spend.inventory import InventoryResolver
from costura.spend.posture import PostureReader
from tests.conftest import SAMPLE_TODAY, seed_sample


def _keys(session: Session, org_id: int, provider: str) -> list[ProviderApiKey]:
    return list(
        session.scalars(
            select(ProviderApiKey).where(
                ProviderApiKey.organization_id == org_id, ProviderApiKey.provider == provider
            )
        )
    )


def test_a_key_carries_its_owner_and_a_last_use_from_the_ledger(db_session: Session) -> None:
    org_id = seed_sample(db_session).organization.id
    keys = _keys(db_session, org_id, "anthropic")
    resolver = InventoryResolver(db_session, org_id, "anthropic")
    posture = PostureReader(db_session, org_id, resolver, keys)
    key = next(k for k in keys if k.external_id == "apikey_demo_prod_agent")

    body = api_key_out(resolver, key, posture)

    assert (body.owner, body.owner_source) == ("bruno@sample.example", "creator")
    assert body.creator_left is False
    assert body.last_used_source == "derived"
    assert body.last_used_at is not None and body.last_used_at.date() < SAMPLE_TODAY


def test_a_reported_last_use_wins_over_the_ledger(db_session: Session) -> None:
    org_id = seed_sample(db_session).organization.id
    keys = _keys(db_session, org_id, "openai")
    resolver = InventoryResolver(db_session, org_id, "openai")
    posture = PostureReader(db_session, org_id, resolver, keys)
    reported = [k for k in keys if k.last_used_at is not None]

    assert reported
    facts = posture.of(reported[0])
    assert (facts.last_used_at, facts.last_used_source) == (reported[0].last_used_at, "reported")


def test_a_creator_who_left_is_flagged(db_session: Session) -> None:
    org_id = seed_sample(db_session).organization.id
    keys = _keys(db_session, org_id, "anthropic")
    key = next(k for k in keys if k.external_id == "apikey_demo_prod_agent")
    creator = db_session.scalars(
        select(ProviderUser).where(
            ProviderUser.organization_id == org_id,
            ProviderUser.provider == "anthropic",
            ProviderUser.external_id == key.created_by_external_id,
        )
    ).one()
    creator.missing_since = creator.last_seen_at
    db_session.commit()

    resolver = InventoryResolver(db_session, org_id, "anthropic")
    facts = PostureReader(db_session, org_id, resolver, keys).of(key)

    assert facts.creator_left is True
