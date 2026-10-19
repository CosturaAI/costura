"""Teams: a line counts under its key's team, else its person's, else its workspace's;
unmapped spend reads "(no team)"; a team budget sums the team row; the routes map and
unmap entities and refuse what the inventory does not hold."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from costura.errors import InvalidInput, NotFound
from costura.models.budget import PERSON_BUDGET_PROVIDER
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.spend import teams
from costura.spend.budgets import InvalidBudget, budget_statuses, delete_budget, set_budget
from costura.spend.usage import usage_report
from tests.conftest import ORG_ID
from tests.support.spend import AUGUST
from tests.test_person_budgets import ALICE, _synced

KEY = "apikey_redacted_1"
WORKSPACE = "wrkspc_redacted_a"


def _rows(db_session: Session) -> dict[str | None, Decimal]:
    report = usage_report(
        db_session, org_id=ORG_ID, provider="all", window=AUGUST, dimension="team"
    )
    return {row.label: row.amount or Decimal("0") for row in report.rows}


def _amount(db_session: Session, dimension: str, key: str) -> Decimal:
    report = usage_report(
        db_session, org_id=ORG_ID, provider="all", window=AUGUST, dimension=dimension
    )
    return sum((r.amount or Decimal("0") for r in report.rows if r.key == key), Decimal("0"))


def test_spend_follows_key_then_person_then_workspace(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client)
    before = _rows(db_session)
    assert list(before) == ["(no team)", "(unallocated cost)"]
    total = sum(before.values(), Decimal("0"))

    teams.set_team(db_session, ORG_ID, "growth", "Growth")
    teams.set_team(db_session, ORG_ID, "platform", "Platform")
    teams.set_member(
        db_session, ORG_ID, "platform", "workspace", "anthropic", WORKSPACE, user_id=None
    )
    teams.set_member(
        db_session, ORG_ID, "growth", "person", "all", " Alice@Example.com ", user_id=None
    )
    teams.set_member(db_session, ORG_ID, "growth", "api_key", "anthropic", KEY, user_id=None)

    rows = _rows(db_session)
    assert sum(rows.values(), Decimal("0")) == total
    assert rows["Growth"] == _amount(db_session, "person", ALICE) + _amount(
        db_session, "api_key", KEY
    )
    assert "Platform" in rows
    assert "(no team)" in rows

    teams.set_member(db_session, ORG_ID, "platform", "api_key", "anthropic", KEY, user_id=None)
    moved = _rows(db_session)
    assert moved["Growth"] == _amount(db_session, "person", ALICE)
    assert moved["Platform"] == rows["Platform"] + _amount(db_session, "api_key", KEY)
    assert [
        m.external_id
        for v in teams.list_teams(db_session, ORG_ID)
        for m in v.members
        if v.team.slug == "growth"
    ] == [ALICE]


def test_a_team_budget_sums_the_team_row_and_goes_with_the_team(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client)
    teams.set_team(db_session, ORG_ID, "growth", "Growth")
    teams.set_member(db_session, ORG_ID, "growth", "person", "all", ALICE, user_id=None)
    set_budget(db_session, ORG_ID, PERSON_BUDGET_PROVIDER, "team", "growth", Decimal("100"), None)

    (status,) = [
        s
        for s in budget_statuses(db_session, ORG_ID, "all", AUGUST)
        if s.budget.scope_kind == "team"
    ]
    assert status.spent == _amount(db_session, "person", ALICE)
    assert status.projected is None

    with pytest.raises(InvalidBudget):
        set_budget(db_session, ORG_ID, "anthropic", "team", "growth", Decimal("1"), None)
    with pytest.raises(InvalidBudget):
        set_budget(db_session, ORG_ID, "all", "team", "growth", Decimal("1"), None, period="week")

    teams.delete_team(db_session, ORG_ID, "growth")
    assert not delete_budget(db_session, ORG_ID, "all", "team", "growth")
    assert _rows(db_session).get("Growth") is None


def test_mappings_refuse_unknown_teams_entities_and_slugs(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client)
    with pytest.raises(InvalidInput):
        teams.set_team(db_session, ORG_ID, "Bad Slug", "x")
    with pytest.raises(NotFound):
        teams.set_member(db_session, ORG_ID, "nope", "person", "all", ALICE, user_id=None)
    teams.set_team(db_session, ORG_ID, "growth", "Growth")
    with pytest.raises(NotFound):
        teams.set_member(
            db_session, ORG_ID, "growth", "api_key", "anthropic", "k_none", user_id=None
        )
    with pytest.raises(InvalidInput):
        teams.set_member(db_session, ORG_ID, "growth", "person", "anthropic", ALICE, user_id=None)


def test_routes_create_map_list_and_remove(
    client: TestClient, db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client)
    db_session.commit()
    slug = client.get("/api/v1/orgs").json()[0]["slug"]
    base = f"/api/v1/orgs/{slug}/teams"

    assert client.put(f"{base}/growth", json={"name": "Growth"}).status_code == 200
    saved = client.put(f"{base}/growth/members/workspace/anthropic/{WORKSPACE}")
    assert saved.status_code == 200
    (team,) = saved.json()["teams"]
    assert (team["name"], team["members"][0]["label"]) == ("Growth", f"Platform ({WORKSPACE})")
    assert client.put(f"{base}/growth/members/api_key/anthropic/k_none").status_code == 404

    usage = client.get(
        f"/api/v1/orgs/{slug}/providers/all/months/2026-08/usage", params={"by": "team"}
    ).json()
    assert "Growth" in {row["label"] for row in usage["rows"]}

    removed = client.delete(f"{base}/growth/members/workspace/anthropic/{WORKSPACE}")
    assert removed.status_code == 204
    assert client.delete(f"{base}/growth").status_code == 204
    assert client.get(base).json() == {"teams": []}
