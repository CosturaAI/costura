"""The sample organization: the published dataset matches its manifest, refreshes keep the
days already published, a failed build keeps the old sample, a tenant named `demo` is never
published, and the API serves the sample publicly and refuses every write."""

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from costura.api.deps import DEMO_READ_ONLY
from costura.config import get_settings
from costura.demo import (
    DemoBusy,
    DemoSlugTaken,
    demo_status,
    refresh_demo,
    refresh_if_stale,
    seed_demo,
)
from costura.demo import lifecycle as demo_lifecycle
from costura.demo.lifecycle import cleanup_abandoned, demo_org
from costura.demo.manifest import DATASET_VERSION, DEMO_NAME, OPENROUTER_LATE_USAGE, PROVIDERS
from costura.models import (
    Organization,
    ProviderAccount,
    ProviderApiKey,
    SchedulerRun,
    SpendAnomaly,
    SpendCostLine,
    User,
)
from costura.models.organization import DEMO_ORG_SLUG
from costura.ops import demo_seed
from costura.orgs import create_org, get_org, reset_organization
from costura.spend.budgets import budget_statuses
from costura.spend.membership import membership
from costura.spend.query import QuerySpec, query_spend
from costura.spend.reconcile import reconcile
from costura.spend.summary import summary
from costura.spend.window import Window
from tests.conftest import SAMPLE_TODAY, seed_sample, sign_in

TODAY = SAMPLE_TODAY
DEMO = f"/api/v1/orgs/{DEMO_ORG_SLUG}"
ANTHROPIC = f"{DEMO}/providers/anthropic"
SMALL = {"months": 2, "daily_cycles": 0}

# Every anomaly the full build publishes on TODAY: (provider, kind, series kind, series, day).
# The 90-day retention keeps the episodes after mid-June; the stories repeat every 28 days.
EXPECTED_ANOMALIES = {
    ("anthropic", "spike", "account", "user_demo_carla", date(2026, 7, 1)),
    ("anthropic", "spike", "account", "user_demo_carla", date(2026, 7, 29)),
    ("anthropic", "spike", "account", "user_demo_carla", date(2026, 8, 26)),
    ("anthropic", "spike", "api_key", "apikey_demo_prod_agent", date(2026, 7, 22)),
    ("anthropic", "spike", "api_key", "apikey_demo_prod_agent", date(2026, 8, 19)),
    ("anthropic", "spike", "org", "__org__", date(2026, 7, 1)),
    ("anthropic", "spike", "org", "__org__", date(2026, 7, 22)),
    ("anthropic", "spike", "org", "__org__", date(2026, 8, 19)),
    ("openai", "drop", "api_key", "key_demo_support_prod", date(2026, 8, 24)),
    ("openai", "new_principal", "api_key", "key_demo_support_v2", date(2026, 8, 24)),
    ("openrouter", "drop", "api_key", "or_demo_gateway", date(2026, 7, 6)),
    ("openrouter", "drop", "api_key", "or_demo_gateway", date(2026, 8, 3)),
    ("openrouter", "drop", "api_key", "or_demo_gateway", date(2026, 8, 31)),
    ("openrouter", "drop", "api_key", "or_demo_gateway", date(2026, 9, 1)),
    ("openrouter", "drop", "org", "__org__", date(2026, 7, 6)),
    ("openrouter", "drop", "org", "__org__", date(2026, 8, 3)),
    ("openrouter", "drop", "org", "__org__", date(2026, 8, 31)),
    ("openrouter", "drop", "org", "__org__", date(2026, 9, 1)),
}
EXPECTED_ACCOUNTS = {
    ("anthropic", "Acme"),
    ("cursor", "Acme"),
    ("openai", "Acme Labs"),
    ("openai", "Acme Platform"),
    ("openrouter", "Acme"),
}
EXPECTED_KEYS = {
    "anthropic": {
        "legacy-pilot",
        "prod-agent",
        "prod-batch",
        "prod-chat",
        "research-eval",
        "research-notebook",
        "research-trial",
    },
    "openai": {
        "eval-runner",
        "labs-notebook",
        "search-indexer",
        "support-copilot-v2",
        "support-prod",
    },
    "openrouter": {"byok-research", "ci", "ci-legacy", "experiments", "gateway"},
}


def test_full_sample_matches_its_manifest(db_session: Session) -> None:
    result = seed_demo(db_session, today=TODAY)

    assert result.seeded is True
    assert (result.start, result.end) == (date(2025, 9, 1), TODAY)
    org = result.organization
    assert (org.slug, org.name, org.is_demo) == (DEMO_ORG_SLUG, DEMO_NAME, True)
    assert org.demo_dataset_version == DATASET_VERSION
    assert org.demo_generated_through == TODAY - timedelta(days=1)
    assert org.demo_refreshed_at is not None and org.onboarding_dismissed_at is not None
    assert db_session.scalar(select(func.count()).select_from(Organization)) == 2

    accounts = db_session.scalars(
        select(ProviderAccount).where(ProviderAccount.organization_id == org.id)
    ).all()
    assert {(a.provider, a.label) for a in accounts} == EXPECTED_ACCOUNTS
    assert {a.provider for a in accounts} == set(PROVIDERS)
    keys: dict[str, set[str]] = {}
    for key in db_session.scalars(
        select(ProviderApiKey).where(ProviderApiKey.organization_id == org.id)
    ):
        keys.setdefault(key.provider, set()).add(key.name)
    assert keys == EXPECTED_KEYS

    anomalies = db_session.scalars(
        select(SpendAnomaly).where(SpendAnomaly.organization_id == org.id)
    ).all()
    assert {
        (a.provider, a.kind, a.series_kind, a.series_id, a.day) for a in anomalies
    } == EXPECTED_ANOMALIES
    # The curated set has no weekend: the weekly rhythm is in every baseline.
    assert all(a.day.weekday() < 5 for a in anomalies)

    # Reconcile: three providers match their control total, OpenRouter's counts late usage.
    window = Window.for_month("2026-09")
    gaps = {}
    for provider in PROVIDERS:
        report = reconcile(
            db_session, org_id=org.id, provider=provider, window=window, reported_total=Decimal(0)
        )
        assert report.provider_total_latest_run is not None
        gaps[provider] = (
            report.provider_total_latest_run
            - report.costura_total
            + (report.derived_seat_total or 0)
        ).quantize(Decimal("0.01"))
    assert gaps == {
        "anthropic": Decimal("0.00"),
        "openrouter": OPENROUTER_LATE_USAGE,
        "openai": Decimal("0.00"),
        "cursor": Decimal("0.00"),
    }
    headlines = {
        provider: summary(
            db_session, org_id=org.id, provider=provider, month="2026-09", today=TODAY
        ).provider_matches
        for provider in PROVIDERS
    }
    assert headlines == {
        "anthropic": True,
        "openrouter": False,
        "openai": True,
        "cursor": True,
    }

    states = {}
    for provider in PROVIDERS:
        for status in budget_statuses(db_session, org.id, provider, window, today=TODAY):
            states[(provider, status.budget.scope_id)] = (status.percent, status.projected_percent)
    near_spent, near_projected = states[("anthropic", "__org__")]
    assert near_spent < 100 and 90 <= near_projected < 100
    assert states[("openai", "__org__")][0] >= 100
    for healthy in (("anthropic", "wrkspc_demo_research"), ("openrouter", "__org__")):
        assert states[healthy][1] < 60

    runs = db_session.scalars(
        select(SchedulerRun).where(SchedulerRun.organization_id == org.id).order_by(SchedulerRun.id)
    ).all()
    assert len(runs) == 4 * len(EXPECTED_ACCOUNTS)
    assert [(r.provider, r.trigger) for r in runs if r.status != "succeeded"] == [
        ("openrouter", "scheduler")
    ]
    retried = [
        (r.provider, step["step"], step["attempts"])
        for r in runs
        if r.status == "succeeded"
        for step in r.steps
        if step["attempts"] > 1
    ]
    assert retried == [("anthropic", "usage", 2)]
    started = [r.started_at.date() for r in runs]
    assert started == sorted(started) and len(set(started)) == 4
    # A build for an earlier day dates its cycles on the days it stands for.
    assert set(started) == {TODAY - timedelta(days=n) for n in range(4)}

    lifecycle = query_spend(
        db_session,
        org_id=org.id,
        spec=QuerySpec(
            measure="billed_usd",
            dimensions=("model_lifecycle",),
            filters={},
            start=result.start,
            end=TODAY - timedelta(days=1),
            interval="month",
            top=8,
        ),
    )
    assert {row.keys["model_lifecycle"] for row in lifecycle.series} == {
        "Current",
        "Legacy",
        "Deprecated",
        "Unknown",
    }

    second = seed_demo(db_session, today=TODAY)
    assert second.seeded is False and second.rows == result.rows
    assert demo_status(db_session, today=TODAY).current


def test_refresh_keeps_the_days_already_published(db_session: Session) -> None:
    first = seed_demo(db_session, today=TODAY, months=2, daily_cycles=1)
    before = _daily_totals(db_session, first.organization.id)

    later = refresh_demo(db_session, today=TODAY + timedelta(days=1), months=2, daily_cycles=1)

    assert later.organization.id != first.organization.id
    assert later.organization.demo_generated_through == TODAY
    after = _daily_totals(db_session, later.organization.id)
    settled = {k: v for k, v in before.items() if k[1] < TODAY - timedelta(days=1)}
    assert settled and {k: after[k] for k in settled} == settled
    assert max(day for _, day in after) == TODAY
    # One organization holds the sample; the retired one is gone with its rows.
    assert db_session.scalars(select(Organization.slug).order_by(Organization.id)).all() == [
        "default",
        DEMO_ORG_SLUG,
    ]
    assert _cost_lines(db_session, first.organization.id) == 0


def test_a_tenant_named_demo_is_never_published(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant = create_org(db_session, DEMO_ORG_SLUG, "Demo Corp")
    db_session.commit()

    with pytest.raises(DemoSlugTaken, match="never publishes an existing organization"):
        seed_demo(db_session, today=TODAY, **SMALL)
    with pytest.raises(DemoSlugTaken):
        refresh_demo(db_session, today=TODAY, **SMALL)

    db_session.expire_all()
    assert get_org(db_session, DEMO_ORG_SLUG).id == tenant.id
    assert get_org(db_session, DEMO_ORG_SLUG).is_demo is False
    assert db_session.scalar(select(func.count()).select_from(ProviderAccount)) == 0
    assert db_session.scalar(select(func.count()).select_from(Organization)) == 2
    status = demo_status(db_session, today=TODAY)
    assert status.present and not status.current
    assert demo_seed.main(["seed"]) == 1
    assert "is not the sample organization" in capsys.readouterr().err


def test_a_failed_build_keeps_the_published_sample(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    published = seed_sample(db_session).organization.id
    rows = demo_status(db_session, today=TODAY).rows
    real_build = demo_lifecycle.build_dataset

    def broken(session: Session, org: Organization, **kwargs: object):
        real_build(session, org, **kwargs)
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(demo_lifecycle, "build_dataset", broken)
    with pytest.raises(RuntimeError, match="provider exploded"):
        refresh_demo(db_session, today=TODAY + timedelta(days=1), **SMALL)

    db_session.expire_all()
    org = demo_org(db_session)
    assert org is not None and org.id == published and org.is_demo
    assert org.demo_generated_through == TODAY - timedelta(days=1)
    assert demo_status(db_session, today=TODAY).rows == rows
    assert db_session.scalars(select(Organization.slug).order_by(Organization.id)).all() == [
        "default",
        DEMO_ORG_SLUG,
    ]


def test_refresh_deletes_abandoned_builds_and_keeps_owned_organizations(
    db_session: Session,
) -> None:
    abandoned = create_org(db_session, "demo-staging-dead0001", DEMO_NAME)
    abandoned.demo_dataset_version = DATASET_VERSION
    retired = create_org(db_session, "demo-retired-dead0002", DEMO_NAME)
    retired.demo_dataset_version = 1
    # A tenant that picked a look-alike slug has members and no dataset version.
    owned = create_org(db_session, "demo-staging-team", "Team")
    db_session.commit()
    sign_in(db_session, "owner@example.com", owner_of="demo-staging-team")
    assert demo_status(db_session, today=TODAY).abandoned == 2

    seed_sample(db_session)

    slugs = set(db_session.scalars(select(Organization.slug)))
    assert slugs == {"default", DEMO_ORG_SLUG, owned.slug}
    assert cleanup_abandoned(db_session) == 0


def test_concurrent_refresh_is_refused(db_session: Session) -> None:
    from costura.db import get_engine

    with get_engine().connect() as holder:
        holder.execute(text("SELECT pg_advisory_lock(:k)"), {"k": demo_lifecycle.DEMO_LOCK_KEY})
        try:
            with pytest.raises(DemoBusy):
                refresh_demo(db_session, today=TODAY, **SMALL)
        finally:
            holder.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": demo_lifecycle.DEMO_LOCK_KEY}
            )
    assert demo_org(db_session) is None


def test_seed_rebuilds_an_outdated_or_emptied_sample(db_session: Session) -> None:
    first = seed_sample(db_session).organization
    assert seed_sample(db_session).seeded is False

    first.demo_dataset_version = DATASET_VERSION - 1
    db_session.commit()
    assert "dataset version" in demo_status(db_session, today=TODAY).reasons[0]
    rebuilt = seed_sample(db_session)
    assert rebuilt.seeded is True and rebuilt.organization.id != first.id

    # The domain reset still empties the sample; the next seed fills it again.
    assert reset_organization(db_session, rebuilt.organization.id).total > 0
    db_session.expire_all()
    assert "no cost lines" in demo_status(db_session, today=TODAY).reasons
    assert seed_sample(db_session).seeded is True


def test_status_names_what_a_refresh_would_change(db_session: Session) -> None:
    assert demo_status(db_session, today=TODAY).reasons == ["not seeded"]
    seed_sample(db_session)
    assert demo_status(db_session, today=TODAY).current
    later = demo_status(db_session, today=TODAY + timedelta(days=2))
    assert later.reasons == [
        f"generated through {TODAY - timedelta(days=1)}, not {TODAY + timedelta(days=1)}"
    ]
    assert refresh_if_stale(db_session, today=TODAY) is None


def test_the_scheduler_refreshes_only_when_enabled(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura import scheduler

    settings = get_settings()
    calls: list[int] = []
    monkeypatch.setattr(scheduler, "refresh_if_stale", lambda session: calls.append(1) or object())
    assert scheduler.refresh_demo_if_enabled(db_session, settings) is False
    monkeypatch.setattr(settings, "costura_demo_refresh", True)
    assert scheduler.refresh_demo_if_enabled(db_session, settings) is True
    assert calls == [1]

    def explode(session: Session) -> None:
        raise RuntimeError("build failed")

    logged: list[str] = []
    monkeypatch.setattr(scheduler, "refresh_if_stale", explode)
    monkeypatch.setattr(scheduler.log, "exception", lambda message, *args: logged.append(message))
    assert scheduler.refresh_demo_if_enabled(db_session, settings) is False
    assert logged == ["sample organization refresh failed; the published sample is unchanged"]


def test_demo_is_public_and_listed_under_nobody(db_session: Session, client: TestClient) -> None:
    from costura.main import app

    seed_sample(db_session)
    stranger = TestClient(app, headers={"Authorization": sign_in(db_session, "new@example.com")})
    assert membership(db_session, demo_org(db_session).id, _user_id(db_session, "new")) is None

    # A signed-in user without an organization lists none; the sample slug travels in `/me`.
    assert stranger.get("/api/v1/orgs").json() == []
    assert stranger.get("/api/v1/me").json()["demo_org"] == "demo"
    sample = stranger.get(f"/api/v1/orgs/{DEMO_ORG_SLUG}").json()
    assert sample == {
        "slug": "demo",
        "name": DEMO_NAME,
        "is_demo": True,
        "role": None,
        "created_at": sample["created_at"],
    }
    assert stranger.get(f"{DEMO}/members").json() == []

    # No session at all: the sample organization reads, everything else asks to sign in.
    anonymous = TestClient(app)
    assert anonymous.get(f"/api/v1/orgs/{DEMO_ORG_SLUG}").json()["is_demo"] is True
    assert anonymous.get(f"{ANTHROPIC}/months/2026-08/summary").status_code == 200
    assert anonymous.get(f"{DEMO}/setup").status_code == 200
    assert anonymous.get("/api/v1/orgs/default").status_code == 401
    assert anonymous.get("/api/v1/orgs/default/providers/anthropic/months").status_code == 401
    assert anonymous.get("/api/v1/orgs").status_code == 401
    assert anonymous.get("/api/v1/me").status_code == 401
    stale = TestClient(app, headers={"Authorization": "Bearer not-a-session"})
    assert stale.get(f"{ANTHROPIC}/months/2026-08/summary").status_code == 200
    assert stale.get("/api/v1/orgs/default").status_code == 401

    months = stranger.get(f"{DEMO}/providers/all/months").json()["months"]
    assert months == ["2026-09", "2026-08"]
    for provider in PROVIDERS:
        summary = stranger.get(f"{DEMO}/providers/{provider}/months/2026-08/summary").json()
        assert float(summary["total"]) > 0, provider
    keys = stranger.get(f"{ANTHROPIC}/inventory/api-keys").json()["items"]
    assert {k["name"] for k in keys} == EXPECTED_KEYS["anthropic"]
    found = anonymous.get(f"{ANTHROPIC}/inventory/search", params={"q": "ana@"}).json()["items"]
    assert any(item["kind"] == "person" and "ana@" in item["id"] for item in found)
    assert (
        anonymous.get(
            "/api/v1/orgs/default/providers/anthropic/inventory/search", params={"q": "ana@"}
        ).status_code
        == 401
    )
    workspace = stranger.get(f"{ANTHROPIC}/inventory/workspaces/wrkspc_demo_production").json()
    assert workspace["name"] == "Production" and workspace["admins"] == ["ana@sample.example"]
    budgets = stranger.get(f"{DEMO}/providers/openai/months/2026-09/budgets").json()
    assert len(budgets["statuses"]) == 1 and budgets["alerts"]

    # A staging build is invisible: no members and not the public sample.
    staging = create_org(db_session, "demo-staging-peek0001", DEMO_NAME)
    staging.demo_dataset_version = DATASET_VERSION
    db_session.commit()
    assert anonymous.get(f"/api/v1/orgs/{staging.slug}").status_code == 401
    assert stranger.get(f"/api/v1/orgs/{staging.slug}").status_code == 404

    # The owner of `default` lists only `default`; `/me` still names the sample slug.
    assert [o["slug"] for o in client.get("/api/v1/orgs").json()] == ["default"]
    assert client.get("/api/v1/me").json()["demo_org"] == "demo"
    assert client.get(f"/api/v1/orgs/{DEMO_ORG_SLUG}").json()["role"] is None


def test_anonymous_setup_read_of_the_sample_has_no_side_effect(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Orphan-run recovery runs for a member's read; the public read of the sample must not
    start work on the database."""
    from costura import scheduler
    from costura.main import app

    seed_sample(db_session)
    calls: list[int] = []
    monkeypatch.setattr(
        scheduler, "recover_abandoned_runs_if_unlocked", lambda _s, org_id: calls.append(org_id)
    )
    assert TestClient(app).get(f"{DEMO}/setup").status_code == 200
    assert calls == []


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("PUT", f"{ANTHROPIC}/connection", {"admin_key": "sk-ant-admin01-x"}),
        ("DELETE", f"{ANTHROPIC}/connection", None),
        ("POST", f"{ANTHROPIC}/sync", None),
        ("POST", f"{DEMO}/providers/all/sync", None),
        ("PATCH", f"{ANTHROPIC}/anomalies/{{anomaly}}", {"status": "acknowledged"}),
        ("PUT", f"{ANTHROPIC}/budgets/org/__org__", {"amount": "100"}),
        ("DELETE", f"{ANTHROPIC}/budgets/org/__org__", None),
        ("POST", f"{DEMO}/setup/dismiss", None),
        ("POST", f"{DEMO}/setup/reset", None),
    ],
)
def test_every_write_on_demo_answers_403(
    db_session: Session, client: TestClient, method: str, path: str, json: dict | None
) -> None:
    org = seed_sample(db_session).organization
    anomaly = db_session.scalar(
        select(SpendAnomaly.id).where(
            SpendAnomaly.organization_id == org.id, SpendAnomaly.provider == "anthropic"
        )
    )
    before = demo_status(db_session, today=TODAY).rows

    response = client.request(method, path.format(anomaly=anomaly), json=json)

    assert response.status_code == 403
    assert response.json()["detail"] == DEMO_READ_ONLY
    assert demo_status(db_session, today=TODAY).rows == before
    assert db_session.scalar(select(SpendAnomaly.status).where(SpendAnomaly.id == anomaly)) == (
        "open"
    )


def test_seed_runner_prints_what_it_published(
    db_session: Session, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    real_build = demo_lifecycle.build_dataset
    monkeypatch.setattr(
        demo_lifecycle,
        "build_dataset",
        lambda session, org, **kwargs: real_build(session, org, **{**kwargs, **SMALL}),
    )

    assert demo_seed.main([]) == 0
    out = capsys.readouterr().out
    assert f"published demo organization demo ({DEMO_NAME})" in out
    assert "spend_cost_lines" in out
    assert demo_seed.main(["seed"]) == 0
    assert "is current; nothing written" in capsys.readouterr().out

    assert demo_seed.main(["status"]) == 0
    out = capsys.readouterr().out
    assert f"dataset version: {DATASET_VERSION} (current {DATASET_VERSION})" in out
    assert out.rstrip().endswith("current")
    assert demo_seed.main(["status", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["present"] is True
    assert body["version"] == body["current_version"] == DATASET_VERSION
    assert body["current"] is True and body["reasons"] == []
    assert body["rows"]["spend_cost_lines"] > 0

    assert demo_seed.main(["refresh"]) == 0
    assert "published demo organization demo" in capsys.readouterr().out
    db_session.expire_all()
    db_session.query(Organization).filter(Organization.slug == DEMO_ORG_SLUG).update(
        {"demo_generated_through": date(2020, 1, 1)}
    )
    db_session.commit()
    assert demo_seed.main(["status"]) == 1
    assert "stale: generated through 2020-01-01" in capsys.readouterr().out
    assert demo_seed.main(["status", "--json"]) == 1
    body = json.loads(capsys.readouterr().out)
    assert body["current"] is False
    assert body["generated_through"] == "2020-01-01"
    assert body["reasons"][0].startswith("generated through 2020-01-01")


def test_seed_runner_builds_as_of_another_day(
    db_session: Session, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    real_build = demo_lifecycle.build_dataset
    monkeypatch.setattr(
        demo_lifecycle,
        "build_dataset",
        lambda session, org, **kwargs: real_build(session, org, **{**kwargs, **SMALL}),
    )
    assert demo_seed.main(["seed", "--today", "2026-09-15"]) == 0
    assert "[2026-08-01, 2026-09-15)" in capsys.readouterr().out
    demo = db_session.scalars(select(Organization).where(Organization.slug == "demo")).one()
    latest = db_session.scalar(
        select(func.max(SchedulerRun.started_at)).where(SchedulerRun.organization_id == demo.id)
    )
    assert latest is not None
    assert latest.date() == date(2026, 9, 15)
    assert demo_seed.main(["status", "--today", "2026-09-15"]) == 0
    assert "generated through: 2026-09-14" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        demo_seed.main(["seed", "--today", "yesterday"])
    with pytest.raises(SystemExit):
        demo_seed.main(["seed", "--json"])


def test_status_json_is_the_text_report_as_one_object(capsys: pytest.CaptureFixture[str]) -> None:
    status = demo_lifecycle.DemoStatus(
        present=False,
        version=None,
        current_version=DATASET_VERSION,
        generated_through=None,
        refreshed_at=None,
        reasons=["not seeded"],
    )
    assert demo_seed._print_status(status, as_json=True) == 1
    body = json.loads(capsys.readouterr().out)
    assert body == {
        "present": False,
        "version": None,
        "current_version": DATASET_VERSION,
        "generated_through": None,
        "refreshed_at": None,
        "providers": list(PROVIDERS),
        "abandoned": 0,
        "rows": {},
        "current": False,
        "reasons": ["not seeded"],
    }


def test_seed_runner_reports_a_held_lock(
    db_session: Session, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def busy(session: Session, **kwargs: object) -> None:
        raise DemoBusy()

    monkeypatch.setattr("costura.demo.refresh_demo", busy)
    assert demo_seed.main(["refresh"]) == 1
    assert "another demo refresh is running" in capsys.readouterr().err


def _daily_totals(session: Session, org_id: int) -> dict[tuple[str, date], Decimal]:
    day = func.date(SpendCostLine.period_start)
    return {
        (provider, value): amount
        for provider, value, amount in session.execute(
            select(SpendCostLine.provider, day, func.sum(SpendCostLine.amount))
            .where(SpendCostLine.organization_id == org_id)
            .group_by(SpendCostLine.provider, day)
        )
    }


def _cost_lines(session: Session, org_id: int) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(SpendCostLine)
            .where(SpendCostLine.organization_id == org_id)
        )
        or 0
    )


def _user_id(session: Session, local_part: str) -> int:
    return session.scalar(select(User.id).where(User.email == f"{local_part}@example.com"))


def test_sample_ranges_are_capped_for_anonymous_reads(db_session: Session) -> None:
    from costura.main import app

    seed_sample(db_session)
    summary = f"{DEMO}/providers/all/months/2026-09/summary"
    anonymous = TestClient(app)
    year = anonymous.get(summary, params={"start": "2025-09-01", "end": "2026-09-30"})
    assert year.status_code == 200
    decade = anonymous.get(summary, params={"start": "2017-01-01", "end": "2026-09-30"})
    assert decade.status_code == 422
    assert "400 days" in decade.json()["detail"]


def test_sample_providers_are_registered_and_have_clients() -> None:
    from costura.demo.clients import CLIENTS
    from costura.demo.manifest import PROVIDERS as SAMPLE_PROVIDERS
    from costura.providers.registry import PROVIDERS

    assert set(SAMPLE_PROVIDERS) <= set(PROVIDERS)
    assert set(SAMPLE_PROVIDERS) == set(CLIENTS)
