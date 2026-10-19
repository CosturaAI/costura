from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Barrier

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura import scheduler, scheduler_lock, secrets
from costura.config import get_settings
from costura.credentials import set_credential
from costura.db import Base, SessionLocal
from costura.models import Organization, SchedulerRun, User
from costura.ops import claim_owner
from costura.orgs import (
    RESET_TABLES,
    DuplicateSlug,
    InvalidSlug,
    OrganizationBusy,
    OrganizationClaimed,
    UnknownOrganization,
    claim_first_owner,
    create_org,
    get_org,
    reset_organization,
)
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.inventory import run_inventory_sync
from costura.providers.anthropic.sync import run_cost_sync
from costura.spend.ledger import costura_total
from costura.spend.membership import membership
from costura.spend.window import Window
from tests.conftest import ORG_ID, OWNER_EMAIL, anthropic_fixture_handler, sign_in, target
from tests.support.orgs import add_member

FIXTURE_START = datetime(2026, 8, 1, tzinfo=UTC)
FIXTURE_END = datetime(2026, 8, 5, tzinfo=UTC)
AUGUST = Window.for_month("2026-08")


def _slugs(session: Session) -> list[str]:
    return list(session.scalars(select(Organization.slug).order_by(Organization.slug)))


def test_default_org_exists_and_lookup(db_session: Session) -> None:
    assert get_org(db_session, "default").id == ORG_ID
    with pytest.raises(UnknownOrganization):
        get_org(db_session, "nobody")


def test_create_org_validates_slug(db_session: Session) -> None:
    created = create_org(db_session, "acme-co", "Acme")
    assert created.id != ORG_ID
    assert _slugs(db_session) == ["acme-co", "default"]
    with pytest.raises(DuplicateSlug):
        create_org(db_session, "acme-co", "Again")
    for bad in ("Acme", "a", "-acme", "acme co", "x" * 64):
        with pytest.raises(InvalidSlug):
            create_org(db_session, bad, "Bad")


def test_spend_is_scoped_by_org(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    other = create_org(db_session, "other", "Other")
    run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )

    default_total, _ = costura_total(db_session, ORG_ID, "anthropic", AUGUST)
    other_total, _ = costura_total(db_session, other.id, "anthropic", AUGUST)
    assert default_total > 0
    assert other_total == Decimal("0")

    # The same natural key can exist once per organization.
    run_cost_sync(
        db_session,
        target(db_session, other.id, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )
    other_total, _ = costura_total(db_session, other.id, "anthropic", AUGUST)
    assert other_total == default_total


# Tables with an `organization_id` that a reset keeps: membership is who may open the
# organization, and detection settings are how the organization wants to be watched. Neither
# is data synced from a provider.
RESET_KEEPS = {
    "organization_members",
    "organization_invitations",
    "anomaly_settings",
    "webhook_destinations",
    "audit_events",
}


def test_reset_tables_cover_every_table_with_an_organization_id() -> None:
    """A new tenant-scoped table must join `RESET_TABLES` or `RESET_KEEPS`, or a reset would
    leave rows behind by accident."""
    scoped = {
        table.name
        for table in Base.metadata.tables.values()
        if "organization_id" in table.columns
        and table.name != "organizations"
        and table.name not in RESET_KEEPS
    }
    listed = [model.__tablename__ for model in RESET_TABLES]
    assert set(listed) == scoped
    assert len(listed) == len(set(listed))
    # Children before parents: every table referencing another one in the list comes first.
    position = {name: i for i, name in enumerate(listed)}
    for model in RESET_TABLES:
        for fk in model.__table__.foreign_keys:
            parent = fk.column.table.name
            if parent in position:
                assert position[model.__tablename__] < position[parent], (
                    model.__tablename__,
                    parent,
                )


def _client(key: str) -> AnthropicAdminClient:
    return AnthropicAdminClient(
        admin_key=key,
        transport=httpx.MockTransport(anthropic_fixture_handler),
        sleep=lambda _: None,
    )


def _rows(session: Session, org_id: int) -> dict[str, int]:
    return {
        model.__tablename__: session.scalar(
            select(func.count()).select_from(model).where(model.organization_id == org_id)
        )
        or 0
        for model in RESET_TABLES
    }


def test_reset_organization_deletes_only_that_organization(
    db_session: Session, anthropic_client: AnthropicAdminClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(secrets.generate_key()))
    other = create_org(db_session, "other", "Other")
    for org_id in (ORG_ID, other.id):
        run_cost_sync(
            db_session,
            target(db_session, org_id, "anthropic"),
            anthropic_client,
            FIXTURE_START,
            FIXTURE_END,
        )
        run_inventory_sync(db_session, target(db_session, org_id, "anthropic"), anthropic_client)
        set_credential(
            db_session, get_settings(), org_id, "anthropic", "sk-ant-admin01-test", factory=_client
        )
    default_org = db_session.get(Organization, ORG_ID)
    default_org.onboarding_dismissed_at = datetime.now(UTC)
    db_session.commit()
    sign_in(db_session, OWNER_EMAIL, owner_of="default")
    other_before = _rows(db_session, other.id)
    assert other_before["spend_cost_lines"] > 0 and other_before["provider_credentials"] == 1

    result = reset_organization(db_session, ORG_ID)

    # Membership is who may open the organization, not synced data: a reset keeps it.
    assert membership(db_session, ORG_ID, _owner(db_session).id).role == "owner"

    assert result.total > 0
    assert result.deleted["spend_cost_lines"] > 0 and result.deleted["provider_credentials"] == 1
    assert set(result.deleted) == {model.__tablename__ for model in RESET_TABLES}
    assert _rows(db_session, ORG_ID) == dict.fromkeys(result.deleted, 0)
    assert _rows(db_session, other.id) == other_before
    assert db_session.get(Organization, ORG_ID).onboarding_dismissed_at is None
    assert _slugs(db_session) == ["default", "other"]

    assert reset_organization(db_session, ORG_ID).total == 0


@pytest.mark.parametrize("status", ["queued", "running"])
def test_reset_raises_busy_without_deleting_an_active_run(
    db_session: Session,
    anthropic_client: AnthropicAdminClient,
    status: str,
) -> None:
    run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )
    run = SchedulerRun(
        organization_id=ORG_ID,
        provider="anthropic",
        trigger="api",
        status=status,
        steps=[],
    )
    db_session.add(run)
    db_session.commit()
    before = _rows(db_session, ORG_ID)

    if status == "running":
        with SessionLocal() as holder:
            assert scheduler_lock.try_organization_lock(holder, ORG_ID)
            try:
                with pytest.raises(OrganizationBusy, match="sync is active"):
                    reset_organization(db_session, ORG_ID)
            finally:
                scheduler_lock.unlock_organization(holder, ORG_ID)
    else:
        with pytest.raises(OrganizationBusy, match="sync is queued"):
            reset_organization(db_session, ORG_ID)

    assert _rows(db_session, ORG_ID) == before


def test_concurrent_enqueue_and_reset_is_busy_or_fully_reset(
    db_session: Session,
    anthropic_client: AnthropicAdminClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(secrets.generate_key()))
    run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )
    set_credential(
        db_session,
        get_settings(),
        ORG_ID,
        "anthropic",
        "sk-ant-admin01-test",
        factory=_client,
    )
    db_session.commit()
    barrier = Barrier(2)

    def enqueue() -> None:
        with SessionLocal() as session:
            barrier.wait()
            scheduler.enqueue_runs(session, ORG_ID, ["anthropic"], trigger="api")
            session.commit()

    def reset() -> str:
        with SessionLocal() as session:
            barrier.wait()
            try:
                reset_organization(session, ORG_ID)
            except OrganizationBusy:
                return "busy"
            return "reset"

    with ThreadPoolExecutor(max_workers=2) as pool:
        enqueue_future = pool.submit(enqueue)
        reset_future = pool.submit(reset)
        enqueue_future.result()
        outcome = reset_future.result()

    db_session.expire_all()
    rows = _rows(db_session, ORG_ID)
    assert rows["scheduler_runs"] == 1
    if outcome == "busy":
        assert rows["spend_cost_lines"] > 0 and rows["provider_credentials"] == 1
    else:
        assert outcome == "reset"
        assert rows["spend_cost_lines"] == 0 and rows["provider_credentials"] == 0
        assert all(count == 0 for table, count in rows.items() if table != "scheduler_runs")


def test_claim_owner_runner_only_claims_an_organization_without_members(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    assert claim_owner.main(["default", "Ops@Example.com"]) == 0
    assert "ops@example.com is owner of default" in capsys.readouterr().out
    user = db_session.scalar(select(User).where(User.email == "ops@example.com"))
    assert user is not None
    assert membership(db_session, ORG_ID, user.id).role == "owner"

    assert claim_owner.main(["default", "intruder@example.com"]) == 1
    assert "already has members" in capsys.readouterr().err
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(User)) == 1

    assert claim_owner.main(["ghost", "ops@example.com"]) == 1
    assert "unknown organization 'ghost'" in capsys.readouterr().err
    assert claim_owner.main(["default", "nope"]) == 1
    assert "invalid e-mail" in capsys.readouterr().err


def test_claim_first_owner_refuses_an_organization_with_members(db_session: Session) -> None:
    sign_in(db_session, OWNER_EMAIL, owner_of="default")
    with pytest.raises(OrganizationClaimed):
        claim_first_owner(db_session, "default", _owner(db_session))


ORGS = "/api/v1/orgs"


def test_post_orgs_makes_the_caller_owner(client: TestClient, db_session: Session) -> None:
    response = client.post(ORGS, json={"name": " Acme ", "slug": "acme"})
    assert response.status_code == 201
    body = response.json()
    assert body.pop("created_at")
    assert body == {"slug": "acme", "name": "Acme", "is_demo": False, "role": "owner"}
    acme = get_org(db_session, "acme")
    owner = db_session.scalar(select(User).where(User.email == OWNER_EMAIL))
    assert membership(db_session, acme.id, owner.id).role == "owner"
    assert client.get(f"{ORGS}/acme/members").json()[0] | {"created_at": None} == {
        "id": owner.id,
        "email": OWNER_EMAIL,
        "name": None,
        "role": "owner",
        "created_at": None,
        "is_you": True,
    }
    assert client.get(f"{ORGS}/acme/providers/anthropic/months").json() == {"months": []}

    assert client.post(ORGS, json={"name": "Again", "slug": "acme"}).status_code == 409
    for bad in ("Acme", "a", "-acme", "acme co"):
        assert client.post(ORGS, json={"name": "Bad", "slug": bad}).status_code == 422
    assert client.post(ORGS, json={"name": "  ", "slug": "blank"}).status_code == 422
    assert client.post(ORGS, json={"name": "x" * 121, "slug": "long"}).status_code == 422

    forwarded = client.post(
        ORGS, json={"name": "Proxy", "slug": "proxy"}, headers={"X-Forwarded-For": "10.0.0.7"}
    )
    assert forwarded.status_code == 403


def test_post_orgs_refuses_the_operator_and_sample_slugs(client: TestClient) -> None:
    for slug in (get_settings().costura_org, "demo", "demo-staging-1a2b", "demo-retired-x"):
        response = client.post(ORGS, json={"name": "Taken", "slug": slug})
        assert response.status_code == 409
        assert "reserved" in response.json()["detail"]
    assert client.post(ORGS, json={"name": "Demo Labs", "slug": "demo-labs"}).status_code == 201


def test_claim_owner_create_opens_a_missing_organization(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    assert claim_owner.main(["acme", "ops@example.com", "--create"]) == 0
    assert "ops@example.com is owner of acme" in capsys.readouterr().out
    acme = get_org(db_session, "acme")
    user = db_session.scalar(select(User).where(User.email == "ops@example.com"))
    assert user is not None
    assert membership(db_session, acme.id, user.id).role == "owner"
    assert claim_owner.main(["acme", "intruder@example.com", "--create"]) == 1
    assert "already has members" in capsys.readouterr().err
    assert claim_owner.main(["demo", "ops@example.com", "--create"]) == 1
    assert "reserved" in capsys.readouterr().err


def test_patch_orgs_renames_and_keeps_the_slug(client: TestClient, db_session: Session) -> None:
    from costura.main import app

    renamed = client.patch(f"{ORGS}/default", json={"name": "  Acme  "})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Acme"
    assert renamed.json()["slug"] == "default"
    db_session.expire_all()
    assert get_org(db_session, "default").name == "Acme"

    assert client.patch(f"{ORGS}/default", json={"name": "   "}).status_code == 422
    assert client.patch(f"{ORGS}/default", json={"name": "x" * 121}).status_code == 422

    member = TestClient(
        app, headers={"Authorization": sign_in(db_session, "member@example.com", role_in="member")}
    )
    assert member.patch(f"{ORGS}/default", json={"name": "Nope"}).status_code == 403

    create_org(db_session, "demo", "Sample", is_demo=True)
    db_session.commit()
    assert client.patch(f"{ORGS}/demo", json={"name": "Nope"}).status_code == 403


def test_get_orgs_lists_only_memberships_and_foreign_orgs_answer_404(
    client: TestClient, db_session: Session
) -> None:
    from costura.main import app

    create_org(db_session, "other", "Other")
    other_header = sign_in(db_session, "other@example.com", owner_of="other")
    other = TestClient(app, headers={"Authorization": other_header})

    assert [o["slug"] for o in client.get(ORGS).json()] == ["default"]
    assert [o["slug"] for o in other.get(ORGS).json()] == ["other"]

    # Unknown slug and foreign organization are indistinguishable.
    for path in ("setup", "members", "providers/anthropic/months"):
        assert client.get(f"{ORGS}/other/{path}").status_code == 404
        assert client.get(f"{ORGS}/ghost/{path}").status_code == 404
        assert other.get(f"{ORGS}/default/{path}").status_code == 404
    assert client.post(f"{ORGS}/other/setup/dismiss").status_code == 404
    assert other.get(f"{ORGS}/other/setup").status_code == 200

    add_member(db_session, get_org(db_session, "other"), _owner(db_session), "member")
    db_session.commit()
    assert [(o["slug"], o["role"]) for o in client.get(ORGS).json()] == [
        ("default", "owner"),
        ("other", "member"),
    ]
    assert client.get(f"{ORGS}/other/setup").status_code == 200
    # Owners first, so the owner of `other` precedes the member added just above.
    assert [m["email"] for m in client.get(f"{ORGS}/other/members").json()] == [
        "other@example.com",
        "owner@example.com",
    ]


def _owner(session: Session) -> User:
    return session.scalar(select(User).where(User.email == OWNER_EMAIL))
