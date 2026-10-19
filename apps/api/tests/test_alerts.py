"""The in-product anomaly inbox: opt-in per member and organization, unread counts over the
anomalies detected since the opt-in, read marks, and the guards (session, membership, demo)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from costura.api.deps import DEMO_READ_ONLY
from costura.models import AnomalyRead, OrganizationMember, ProviderApiKey, SpendAnomaly
from costura.spend.anomalies import run_detection
from tests.conftest import ORG_ID, account_of, seed_sample, sign_in
from tests.seed import Line, oauth, seed_days, sync_run
from tests.test_anomalies import AUGUST, HISTORY_START, SPIKE_DAY, spiked

ALERTS = "/api/v1/orgs/default/alerts"
EMPTY = {"opted_in": False, "unread_count": 0, "items": [], "signals": [], "unread_by_kind": {}}


@pytest.fixture
def anomalies(db_session: Session) -> None:
    """Three anomalies: the organization total and the key of the synthetic spike, plus a
    Claude Code login spiking on another day."""

    def with_login(day: date) -> list[Line]:
        lines = spiked(day)
        login = Decimal("400") if day == SPIKE_DAY + timedelta(days=2) else Decimal("20")
        lines.append(("ws_b", "claude-sonnet-4", oauth("user_ana"), login))
        return lines

    seed_days(db_session, ORG_ID, "anthropic", HISTORY_START, date(2026, 8, 21), with_login)
    run_detection(db_session, ORG_ID, "anthropic", AUGUST)


def _opted_in_yesterday(db_session: Session) -> None:
    """Move every opt-in a day back so the fixture's anomalies count as new."""
    yesterday = datetime.now(UTC) - timedelta(days=1)
    db_session.execute(update(OrganizationMember).values(anomaly_alerts_since=yesterday))
    db_session.commit()


def test_inbox_is_empty_until_the_member_opts_in(client: TestClient, anomalies: None) -> None:
    assert client.get(ALERTS).json() == EMPTY

    opted = client.put(f"{ALERTS}/settings", json={"opted_in": True})
    assert opted.status_code == 200
    # The opt-in starts now; the fixture's anomalies were detected moments ago, before it.
    assert opted.json()["opted_in"] is True
    assert opted.json()["unread_count"] == 0


def test_mark_all_before_the_opt_in_writes_nothing(
    client: TestClient, db_session: Session, anomalies: None
) -> None:
    marked = client.post(f"{ALERTS}/read", json={"all": True})

    assert marked.status_code == 200 and marked.json() == EMPTY
    assert db_session.scalar(select(func.count()).select_from(AnomalyRead)) == 0


def test_unread_counts_open_anomalies_since_opt_in_and_read_marks_clear_them(
    client: TestClient, db_session: Session, anomalies: None
) -> None:
    client.put(f"{ALERTS}/settings", json={"opted_in": True})
    _opted_in_yesterday(db_session)

    body = client.get(ALERTS).json()
    assert body["opted_in"] is True and body["unread_count"] == 3
    assert body["unread_by_kind"] == {"anomaly": 3}
    assert len(body["items"]) == 3 and all(i["read_at"] is None for i in body["items"])
    assert "impact_share" in body["items"][0] and body["items"][0]["label"]

    first = body["items"][0]["id"]
    marked = client.post(f"{ALERTS}/read", json={"anomaly_ids": [first, 999999]}).json()
    assert marked["unread_count"] == 2
    assert next(i for i in marked["items"] if i["id"] == first)["read_at"] is not None

    # An acknowledged anomaly leaves the unread count, its item stays listed.
    second = next(i["id"] for i in marked["items"] if i["read_at"] is None)
    client.patch(
        f"/api/v1/orgs/default/providers/anthropic/anomalies/{second}",
        json={"status": "acknowledged"},
    )
    assert client.get(ALERTS).json()["unread_count"] == 1

    everything = client.post(f"{ALERTS}/read", json={"all": True}).json()
    assert everything["unread_count"] == 0
    # "All" is the unread set: the acknowledged item was not unread, so it gets no mark.
    assert [i["id"] for i in everything["items"] if i["read_at"] is None] == [second]
    assert db_session.scalar(select(AnomalyRead.anomaly_id).limit(1)) is not None
    assert client.post(f"{ALERTS}/read", json={}).status_code == 422

    # Opting out clears the mark; opting in again starts fresh from now.
    assert client.put(f"{ALERTS}/settings", json={"opted_in": False}).json() == EMPTY
    again = client.put(f"{ALERTS}/settings", json={"opted_in": True}).json()
    assert again["unread_count"] == 0 and again["items"] == []


def test_reads_are_per_user_and_scoped_to_the_organization(
    client: TestClient, db_session: Session, anomalies: None
) -> None:
    from costura.main import app

    client.put(f"{ALERTS}/settings", json={"opted_in": True})
    _opted_in_yesterday(db_session)
    client.post(f"{ALERTS}/read", json={"all": True})

    second = sign_in(db_session, "second@example.com", owner_of="default")
    other = TestClient(app, headers={"Authorization": second})
    assert other.get(ALERTS).json() == EMPTY
    other.put(f"{ALERTS}/settings", json={"opted_in": True})
    _opted_in_yesterday(db_session)
    # The first user's read marks do not count for the second.
    assert other.get(ALERTS).json()["unread_count"] == 3

    # A stranger is not a member: empty inbox, 404 on the writes, 401 without a session.
    stranger = TestClient(app, headers={"Authorization": sign_in(db_session, "x@example.com")})
    assert stranger.get(ALERTS).status_code == 404
    assert TestClient(app).get(ALERTS).status_code == 401
    seed_sample(db_session)
    anomaly_id = db_session.scalar(select(SpendAnomaly.id).limit(1))
    assert anomaly_id is not None
    demo = "/api/v1/orgs/demo/alerts"
    assert stranger.get(demo).json() == EMPTY
    assert TestClient(app).get(demo).status_code == 401
    refused = stranger.put(f"{demo}/settings", json={"opted_in": True})
    assert refused.status_code == 403 and refused.json()["detail"] == DEMO_READ_ONLY
    assert stranger.post(f"{demo}/read", json={"all": True}).status_code == 403


def test_a_key_gap_after_the_opt_in_is_unread_until_marked(
    client: TestClient, db_session: Session
) -> None:
    client.put(f"{ALERTS}/settings", json={"opted_in": True})
    today = datetime.now(UTC).date()
    run = sync_run(db_session, ORG_ID, "anthropic", "api_keys", today, today)
    db_session.add(
        ProviderApiKey(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=account_of(db_session, ORG_ID, "anthropic"),
            sync_run_id=run.id,
            external_id="apikey_orphan",
            name="orphan",
            created_at=datetime.now(UTC),
            status="active",
        )
    )
    db_session.commit()

    body = client.get(ALERTS).json()
    gaps = {s["kind"] for s in body["signals"]}
    assert {"no_owner", "new_key"} <= gaps
    assert body["unread_by_kind"] == {"no_owner": 1, "new_key": 1}
    assert body["unread_count"] == 2
    first = body["signals"][0]
    assert first["read_at"] is None and first["read_reference"] == "apikey_orphan"

    marked = client.post(
        f"{ALERTS}/read",
        json={
            "signals": [
                {"kind": "no_owner", "provider": "anthropic", "read_reference": "apikey_orphan"}
            ]
        },
    ).json()
    assert marked["unread_by_kind"] == {"new_key": 1}
    bogus = {"kind": "anomaly", "provider": "anthropic", "read_reference": "1"}
    assert client.post(f"{ALERTS}/read", json={"signals": [bogus]}).status_code == 422
    assert client.post(f"{ALERTS}/read", json={"all": True}).json()["unread_count"] == 0
