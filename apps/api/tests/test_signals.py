from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.api.presenters.signals import SignalView, signal_out
from costura.models import ProviderApiKey, SpendAnomaly, SpendBudgetAlert
from costura.spend.posture import KeyPosture
from costura.spend.signals import PostureThresholds, collect_signals, posture_gaps
from tests.conftest import SAMPLE_TODAY, seed_sample


def test_signals_join_open_anomalies_and_this_months_budget_alerts(db_session: Session) -> None:
    org_id = seed_sample(db_session).organization.id
    found = collect_signals(db_session, org_id, "all", today=SAMPLE_TODAY)

    open_anomalies = db_session.scalar(
        select(func.count())
        .select_from(SpendAnomaly)
        .where(SpendAnomaly.organization_id == org_id, SpendAnomaly.status == "open")
    )
    budgets_alerted = db_session.scalar(
        select(func.count(func.distinct(SpendBudgetAlert.budget_id))).where(
            SpendBudgetAlert.organization_id == org_id, SpendBudgetAlert.month == "2026-09"
        )
    )
    assert sum(s.kind == "anomaly" for s in found) == open_anomalies
    assert sum(s.kind == "budget" for s in found) == budgets_alerted
    assert open_anomalies and budgets_alerted
    amounts = [s.dollars_at_risk for s in found]
    assert amounts == sorted(amounts, reverse=True)

    view = SignalView(db_session, org_id, "all")
    out = [signal_out(view, s) for s in found]
    assert all(item.label and item.detail for item in out)
    assert any(item.kind == "anomaly" and item.owner for item in out)
    assert all(item.owner is None for item in out if item.kind == "budget")


def test_acknowledged_anomalies_leave_the_queue(db_session: Session) -> None:
    org_id = seed_sample(db_session).organization.id
    before = collect_signals(db_session, org_id, "all", today=SAMPLE_TODAY)
    target = next(s for s in before if s.kind == "anomaly")
    assert target.anomaly is not None
    target.anomaly.status = "acknowledged"
    db_session.commit()

    after = collect_signals(db_session, org_id, "all", today=SAMPLE_TODAY)
    assert target.reference not in {s.reference for s in after if s.kind == "anomaly"}


def _key(**fields: object) -> ProviderApiKey:
    base: dict[str, object] = {
        "provider": "openrouter",
        "external_id": "k",
        "status": "active",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "limit_reported": False,
        "spend_limit": None,
        "principal_type": None,
    }
    return ProviderApiKey(**{**base, **fields})


def _facts(**fields: object) -> KeyPosture:
    base: dict[str, object] = {
        "owner": "ana@example.com",
        "owner_source": "creator",
        "creator_left": False,
        "last_used_at": datetime(2026, 9, 14, tzinfo=UTC),
        "last_used_source": "reported",
    }
    return KeyPosture(**{**base, **fields})  # type: ignore[arg-type]


TODAY = date(2026, 9, 15)


def test_a_governed_key_raises_nothing() -> None:
    assert posture_gaps(_key(), _facts(), TODAY, PostureThresholds()) == []


def test_each_gap_raises_its_own_kind() -> None:
    rules = PostureThresholds()
    assert posture_gaps(_key(), _facts(owner=None), TODAY, rules) == ["no_owner"]
    assert posture_gaps(_key(limit_reported=True), _facts(), TODAY, rules) == ["no_limit"]
    assert (
        posture_gaps(_key(limit_reported=True, spend_limit=Decimal("10")), _facts(), TODAY, rules)
        == []
    )
    assert posture_gaps(_key(), _facts(creator_left=True), TODAY, rules) == ["owner_left"]
    assert posture_gaps(
        _key(created_at=datetime(2026, 9, 12, tzinfo=UTC)), _facts(), TODAY, rules
    ) == ["new_key"]
    assert posture_gaps(
        _key(), _facts(last_used_at=datetime(2026, 8, 1, tzinfo=UTC)), TODAY, rules
    ) == ["idle_active"]
    assert posture_gaps(_key(), _facts(last_used_at=None), TODAY, rules) == ["idle_active"]


def test_an_anthropic_personal_key_dies_with_its_user_so_it_is_not_owner_left() -> None:
    personal = _key(provider="anthropic", principal_type="user")
    workspace = _key(provider="anthropic", principal_type=None)
    rules = PostureThresholds()
    assert posture_gaps(personal, _facts(creator_left=True), TODAY, rules) == []
    assert posture_gaps(workspace, _facts(creator_left=True), TODAY, rules) == ["owner_left"]


def test_thresholds_move_the_idle_and_new_windows() -> None:
    key = _key(created_at=datetime(2026, 9, 1, tzinfo=UTC))
    facts = _facts(last_used_at=datetime(2026, 9, 5, tzinfo=UTC))
    assert posture_gaps(key, facts, TODAY, PostureThresholds()) == []
    tight = PostureThresholds(idle_days=7, new_key_days=30)
    assert posture_gaps(key, facts, TODAY, tight) == ["new_key", "idle_active"]
