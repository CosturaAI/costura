"""Who to contact about an anomaly: key creators, workspace administrators, the owners behind
the root causes of organization and model anomalies, and the Costura organization owners
closing every list. Runs on the sample organization's inventory and on a bare organization."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.demo.lifecycle import demo_org
from costura.models import OwnerAssignment, ProviderApiKey, SpendAnomaly
from costura.spend.inventory import InventoryResolver
from costura.spend.owners import (
    ACCOUNT_USER,
    ASSIGNED,
    COSTURA_SOURCE,
    KEY_CREATOR,
    ORGANIZATION_OWNER,
    WORKSPACE_ADMIN,
    Owner,
    account_owners,
    anomaly_owners,
    key_owners,
    load_assignments,
    organization_owners,
    owners_gap,
    workspace_owners,
)
from tests.conftest import account_of, seed_sample, sign_in
from tests.seed import sync_run

TODAY = date(2026, 9, 15)
DEMO = "/api/v1/orgs/demo/providers"
PRODUCTION = "Production (wrkspc_demo_production)"


def _resolver(session: Session) -> InventoryResolver:
    return InventoryResolver(session, demo_org(session).id, "anthropic")


def test_key_owners_are_the_creator_then_the_workspace_admins(db_session: Session) -> None:
    seed_sample(db_session)
    resolver = _resolver(db_session)

    assert key_owners(resolver, "anthropic", "apikey_demo_prod_agent") == [
        Owner("bruno@sample.example", KEY_CREATOR, "prod-agent (apikey_demo_prod_agent)"),
        Owner("ana@sample.example", WORKSPACE_ADMIN, PRODUCTION),
    ]
    # A creator who also administers the workspace appears once, as the creator.
    key_anomaly = SpendAnomaly(
        provider="anthropic",
        series_kind="api_key",
        series_id="apikey_demo_prod_chat",
        root_causes=[],
    )
    assert anomaly_owners(resolver, key_anomaly, []) == [
        Owner("ana@sample.example", KEY_CREATOR, "prod-chat (apikey_demo_prod_chat)")
    ]
    assert key_owners(resolver, "anthropic", "apikey_unknown") == []


def test_workspace_owners_and_default_workspace(db_session: Session) -> None:
    seed_sample(db_session)
    resolver = _resolver(db_session)

    assert workspace_owners(resolver, "anthropic", "wrkspc_demo_research") == [
        Owner("carla@sample.example", WORKSPACE_ADMIN, "Research (wrkspc_demo_research)")
    ]
    assert workspace_owners(resolver, "anthropic", "(default workspace)") == []
    assert workspace_owners(resolver, "anthropic", "wrkspc_unknown") == []


def test_org_anomaly_owners_follow_the_root_causes(db_session: Session) -> None:
    seed_sample(db_session)
    org_id = demo_org(db_session).id
    row = db_session.scalar(
        select(SpendAnomaly).where(
            SpendAnomaly.organization_id == org_id,
            SpendAnomaly.provider == "anthropic",
            SpendAnomaly.series_kind == "org",
        )
    )
    assert row is not None and row.root_causes

    org_owners = organization_owners(db_session, org_id)
    owners = anomaly_owners(_resolver(db_session), row, org_owners)

    # The spiking key (prod-agent) leads to its creator, then the administrator of its
    # workspace; nobody owns `demo`, so the list ends with the inventory people only.
    assert org_owners == []
    assert owners[:2] == [
        Owner("bruno@sample.example", KEY_CREATOR, "prod-agent (apikey_demo_prod_agent)"),
        Owner("ana@sample.example", WORKSPACE_ADMIN, PRODUCTION),
    ]
    assert all(o.role != ORGANIZATION_OWNER for o in owners)
    assert len({o.email for o in owners}) == len(owners)


def test_owners_gap_explains_why_the_inventory_names_nobody(db_session: Session) -> None:
    """A key the listing does not include (the usage report names it by name only), a key
    whose creator id has no member record, a workspace without administrators, and an org
    anomaly whose causes lead nowhere each get a sentence; a resolved key gets None."""
    seed_sample(db_session)
    org_id = demo_org(db_session).id
    run = sync_run(db_session, org_id, "anthropic", "api_keys", TODAY, TODAY)
    db_session.add(
        ProviderApiKey(
            organization_id=org_id,
            provider="anthropic",
            provider_account_id=account_of(db_session, org_id, "anthropic"),
            sync_run_id=run.id,
            external_id="apikey_orphan",
            name="orphan",
            workspace_external_id="wrkspc_demo_research",
            created_by_external_id="user_gone",
            status="active",
        )
    )
    db_session.add(
        ProviderApiKey(
            organization_id=org_id,
            provider="anthropic",
            provider_account_id=account_of(db_session, org_id, "anthropic"),
            sync_run_id=run.id,
            external_id="apikey_lonely",
            name="lonely",
            workspace_external_id="wrkspc_unknown",
            created_by_external_id=None,
            status="active",
        )
    )
    db_session.flush()
    resolver = _resolver(db_session)

    def key(series_id: str) -> SpendAnomaly:
        return SpendAnomaly(
            provider="anthropic", series_kind="api_key", series_id=series_id, root_causes=[]
        )

    assert owners_gap(resolver, key("apikey_demo_prod_agent")) is None
    assert owners_gap(resolver, key("terminal-bench-mukerem")) == (
        "The provider's key listing does not include this key; the usage report names it only "
        "as `terminal-bench-mukerem`. Nobody is recorded as its creator."
    )
    # Its workspace has an administrator, so only the creator is the gap; the admin is named.
    assert owners_gap(resolver, key("apikey_orphan")) is None
    assert owners_gap(resolver, key("apikey_lonely")) == (
        "The provider records no creator for this key; the provider lists no administrators "
        "for wrkspc_unknown (not in inventory)."
    )
    login = SpendAnomaly(
        provider="anthropic", series_kind="account", series_id="user_demo_carla", root_causes=[]
    )
    assert owners_gap(resolver, login) is None
    assert account_owners(resolver, "anthropic", "user_demo_carla") == [
        Owner("carla@sample.example", ACCOUNT_USER, "login user_demo_carla")
    ]
    stranger = SpendAnomaly(
        provider="anthropic", series_kind="account", series_id="user_gone", root_causes=[]
    )
    assert owners_gap(resolver, stranger) == (
        "The login id `user_gone` is not in the provider's member list, so it maps to no e-mail."
    )
    org = SpendAnomaly(
        provider="anthropic",
        series_kind="org",
        series_id="org",
        root_causes=[{"kind": "api_key", "id": "terminal-bench-mukerem"}],
    )
    assert owners_gap(resolver, org) == (
        "None of the top contributors is tied to a person in the provider inventory."
    )


def test_detail_route_serves_owners_publicly_on_demo_and_owners_close_the_list(
    db_session: Session, client: TestClient
) -> None:
    from costura.main import app

    seed_sample(db_session)
    anonymous = TestClient(app)
    listed = anonymous.get(f"{DEMO}/anthropic/months/2026-08/anomalies").json()["anomalies"]
    assert listed
    details = [(row, anonymous.get(f"{DEMO}/anthropic/anomalies/{row['id']}")) for row in listed]
    owned, detail = next((row, response) for row, response in details if response.json()["owners"])
    assert detail.status_code == 200
    body = detail.json()
    assert body["owners"] and all(o["email"].endswith("@sample.example") for o in body["owners"])
    assert body["owners_gap"] is None
    assert len(body["series"]) == 57

    # The `default` owner opens their own anomaly-less organization: 404 on a demo id.
    foreign = client.get(f"/api/v1/orgs/default/providers/all/anomalies/{owned['id']}")
    assert foreign.status_code == 404
    # A second Costura owner of `demo` would close the list; give `demo` one and check.
    sign_in(db_session, "ops@costura.example", owner_of="demo")
    body = anonymous.get(f"{DEMO}/anthropic/anomalies/{owned['id']}").json()
    assert body["owners"][-1] == {
        "email": "ops@costura.example",
        "role": ORGANIZATION_OWNER,
        "source": COSTURA_SOURCE,
        "note": None,
    }


def test_an_assigned_contact_comes_first_and_closes_the_gap(db_session: Session) -> None:
    """A contact assigned in Costura to a key, or to its workspace, leads the list even when the
    inventory names nobody; `owners_gap` then has nothing to explain."""
    seed_sample(db_session)
    org_id = demo_org(db_session).id
    run = sync_run(db_session, org_id, "anthropic", "api_keys", TODAY, TODAY)
    db_session.add(
        ProviderApiKey(
            organization_id=org_id,
            provider="anthropic",
            provider_account_id=account_of(db_session, org_id, "anthropic"),
            sync_run_id=run.id,
            external_id="apikey_lonely",
            name="lonely",
            workspace_external_id="wrkspc_unknown",
            created_by_external_id=None,
            status="active",
        )
    )
    db_session.add(
        OwnerAssignment(
            organization_id=org_id,
            provider="anthropic",
            provider_account_id=account_of(db_session, org_id, "anthropic"),
            kind="workspace",
            external_id="wrkspc_unknown",
            email="gateway-oncall@sample.example",
            note="on-call rotation",
        )
    )
    db_session.flush()
    resolver = _resolver(db_session)
    lonely = SpendAnomaly(
        provider="anthropic", series_kind="api_key", series_id="apikey_lonely", root_causes=[]
    )
    assert owners_gap(resolver, lonely) is not None
    assignments = load_assignments(db_session, org_id, "anthropic")
    assert owners_gap(resolver, lonely, assignments) is None
    assert anomaly_owners(resolver, lonely, [], assignments) == [
        Owner(
            "gateway-oncall@sample.example",
            ASSIGNED,
            "wrkspc_unknown (not in inventory)",
            "on-call rotation",
        )
    ]

    # A key-level assignment beats the creator, and a key absent from the inventory keeps it.
    db_session.add(
        OwnerAssignment(
            organization_id=org_id,
            provider="anthropic",
            provider_account_id=account_of(db_session, org_id, "anthropic"),
            kind="api_key",
            external_id="apikey_demo_prod_agent",
            email="platform@sample.example",
        )
    )
    db_session.add(
        OwnerAssignment(
            organization_id=org_id,
            provider="anthropic",
            provider_account_id=account_of(db_session, org_id, "anthropic"),
            kind="api_key",
            external_id="terminal-bench-mukerem",
            email="mukerem@sample.example",
        )
    )
    db_session.flush()
    assignments = load_assignments(db_session, org_id, "anthropic")
    agent = key_owners(resolver, "anthropic", "apikey_demo_prod_agent", assignments)
    assert [o.email for o in agent] == [
        "platform@sample.example",
        "bruno@sample.example",
        "ana@sample.example",
    ]
    assert agent[0].role == ASSIGNED and agent[1].role == KEY_CREATOR
    assert key_owners(resolver, "anthropic", "terminal-bench-mukerem", assignments) == [
        Owner("mukerem@sample.example", ASSIGNED, "terminal-bench-mukerem (not in inventory)")
    ]


def test_owner_routes_are_member_writes_and_the_detail_page_reads_them(
    db_session: Session, client: TestClient
) -> None:
    """A member (not only an owner) assigns a contact; the anomaly detail names it first with
    the note; the demo organization refuses the write; an unknown kind or e-mail is 422."""
    from costura.main import app

    seed_sample(db_session)
    sign_in(db_session, "owner@costura.example", owner_of="default")
    from costura import auth
    from costura.orgs import get_org
    from tests.support.orgs import add_member

    member = auth.sign_in_dev(db_session, "member@costura.example")
    add_member(db_session, get_org(db_session, "default"), member.user, "member")
    db_session.commit()
    api = TestClient(app)
    api.headers["Authorization"] = f"Bearer {member.token}"
    base = "/api/v1/orgs/default/providers/anthropic/owners"
    assert api.get(base).json() == []
    put = api.put(
        f"{base}/api_key/apikey_x",
        json={"email": " Ops@Example.com ", "note": "  gateway on-call "},
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["email"] == "ops@example.com"
    assert body["note"] == "gateway on-call"
    assert body["assigned_by"] == "member@costura.example"
    assert body["label"] == "apikey_x (not in inventory)"
    assert [row["external_id"] for row in api.get(base).json()] == ["apikey_x"]

    assert api.put(f"{base}/model/x", json={"email": "a@b.c"}).status_code == 422
    assert api.put(f"{base}/api_key/x", json={"email": "nope"}).status_code == 422
    assert api.delete(f"{base}/api_key/missing").status_code == 404
    assert api.delete(f"{base}/api_key/apikey_x").status_code == 204
    assert api.get(base).json() == []

    # The sample organization is read-only for everyone, including its owner.
    demo_owner = TestClient(app)
    demo_owner.headers["Authorization"] = sign_in(
        db_session, "ops@costura.example", owner_of="demo"
    )
    refused = demo_owner.put(
        f"{DEMO}/anthropic/owners/api_key/terminal-bench-mukerem", json={"email": "m@x.y"}
    )
    assert refused.status_code == 403

    # Reading through the anomaly detail: assign at the database level on demo and read back.
    anonymous = TestClient(app)
    listed = anonymous.get(f"{DEMO}/anthropic/months/2026-08/anomalies").json()["anomalies"]
    mine = next(a for a in listed if a["series_kind"] == "api_key")
    db_session.add(
        OwnerAssignment(
            organization_id=demo_org(db_session).id,
            provider="anthropic",
            provider_account_id=account_of(db_session, demo_org(db_session).id, "anthropic"),
            kind="api_key",
            external_id=mine["series_id"],
            email="contractor@sample.example",
            note="research contractor",
        )
    )
    db_session.commit()
    detail = anonymous.get(f"{DEMO}/anthropic/anomalies/{mine['id']}").json()
    assert detail["owners"][0] == {
        "email": "contractor@sample.example",
        "role": ASSIGNED,
        "source": mine["label"],
        "note": "research contractor",
    }
    assert detail["owners_gap"] is None
