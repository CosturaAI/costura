"""The evidence behind one anomaly: the recomputed baseline with its
samples and margin rule, every noise filter with its verdict, the day's rows against their
own history, the runs behind the data and the series' other anomalies."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from costura.models import SpendAllocatedLine, SpendAnomaly, SpendCostLine
from costura.spend.anomalies import run_detection
from costura.spend.anomaly_baseline import baseline_detail
from costura.spend.evidence import anomaly_evidence
from tests.seed import Line, seed_days, sync_run
from tests.support.queries import counted_statements
from tests.test_anomalies import (
    AUGUST,
    HISTORY_START,
    PROVIDER,
    SEED_END,
    SPIKE_DAY,
    TODAY,
    series,
    spiked,
)

CHECK_NAMES = [
    "above_upper_bound",
    "amount_floor",
    "impact_floor",
    "organization_share",
    "recent_average",
    "previous_day",
    "history",
    "suppression",
]
DROP_CHECK_NAMES = [
    "below_lower_bound",
    "expected_floor",
    "impact_floor",
    "complete_day",
    "provider_reported",
    "recent_average",
    "history",
    "suppression",
]
NEW_PRINCIPAL_CHECK_NAMES = [
    "new_series",
    "new_principal_floor",
    "new_principal_share",
    "suppression",
]


# The organization page runs the most statements: four day breakdowns over one shared
# inventory load and one allocation decision, plus unit economics, the volume, mix and price
# split, data quality, history, the organization's anomaly settings and the provider accounts
# (two reads: the resolver's label map and the allocation decision's account list).
QUERY_CEILING = 37


def _anomaly(session: Session, kind: str) -> SpendAnomaly:
    return session.scalars(select(SpendAnomaly).where(SpendAnomaly.series_kind == kind)).one()


def test_margin_rule_names_the_candidate_that_fixed_the_upper_bound() -> None:
    anchor = SPIKE_DAY
    # Flat history: MAD is 0, so 20% of the median (20) beats the 5 USD floor.
    flat = baseline_detail(series(dict.fromkeys(range(1, 71), Decimal("100")), anchor), anchor)
    assert flat is not None
    assert (flat.method, len(flat.sample_days), flat.margin_rule) == ("weekday", 8, "relative")
    assert flat.sample_days[0] == anchor - timedelta(days=7)
    assert (flat.median, flat.mad, flat.margin, flat.upper) == (100, 0, 20, 120)

    # A small median: 20% of 10 is 2, below the 5 USD floor.
    small = baseline_detail(series(dict.fromkeys(range(1, 71), Decimal("10")), anchor), anchor)
    assert small is not None
    assert (small.margin_rule, small.margin, small.upper) == ("absolute", 5, 15)

    # Spread-out Tuesdays: 3 x 1.4826 x MAD beats both floors.
    spread = {offset: Decimal("100") for offset in range(1, 71)}
    for k, amount in enumerate((40, 160, 40, 160, 40, 160, 40, 160), start=1):
        spread[7 * k] = Decimal(amount)
    wide = baseline_detail(series(spread, anchor), anchor)
    assert wide is not None
    assert (wide.median, wide.mad, wide.margin_rule) == (100, 60, "mad")
    assert wide.margin == Decimal("3") * Decimal("1.4826") * 60


def test_evidence_matches_the_detector_and_every_check_holds(
    db_session: Session, org_id: int
) -> None:
    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, spiked)
    run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    row = _anomaly(db_session, "org")

    evidence = anomaly_evidence(db_session, row)

    detail = evidence.baseline
    assert detail is not None
    assert detail.method == "weekday" and len(detail.sample_days) == 8
    assert all(amount == Decimal("100") for amount in detail.sample_amounts)
    assert (detail.median, detail.upper, detail.margin_rule) == (100, 120, "relative")
    assert evidence.actual_now == Decimal("540") and evidence.matches_stored(row)
    assert [c.name for c in evidence.checks] == CHECK_NAMES
    assert all(c.passed for c in evidence.checks)
    upper = evidence.checks[0]
    assert (upper.observed, upper.threshold) == (Decimal("540"), Decimal("120"))
    recent = next(c for c in evidence.checks if c.name == "recent_average")
    # Aug 4-10: Tue-Fri 100, Sat-Sun 20, Mon 100 -> mean 77.14, x 1.2.
    assert recent.threshold is not None and recent.threshold.quantize(Decimal("0.01")) == Decimal(
        "92.57"
    )
    # The org total has no org-share floor.
    share = next(c for c in evidence.checks if c.name == "organization_share")
    assert share.threshold == Decimal("540") * Decimal("0.005")
    assert evidence.history == []


def test_a_resync_that_changes_the_day_is_visible(db_session: Session, org_id: int) -> None:
    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, spiked)
    run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    row = _anomaly(db_session, "org")
    spike_start = datetime(SPIKE_DAY.year, SPIKE_DAY.month, SPIKE_DAY.day, tzinfo=UTC)
    for table in (SpendCostLine, SpendAllocatedLine):
        db_session.execute(
            update(table)
            .where(table.period_start == spike_start, table.workspace_id == "ws_a")
            .values(amount=Decimal("110"))
        )
    later = sync_run(db_session, org_id, PROVIDER, "cost_report", SPIKE_DAY, SEED_END)
    later.finished_at = row.detected_at + timedelta(minutes=5)
    db_session.commit()

    evidence = anomaly_evidence(db_session, row)

    assert evidence.actual_now == Decimal("150") and not evidence.matches_stored(row)
    # 150 is above the 120 bound and the 7-day average, and 50 above the expected 100.
    assert [c.name for c in evidence.checks if not c.passed] == []
    quality = evidence.data_quality
    assert quality is not None and quality.changed_since_detection
    assert [run.endpoint for run in quality.runs][:1] == ["cost_report"]


def test_a_control_total_sync_does_not_count_as_a_change(db_session: Session, org_id: int) -> None:
    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, spiked)
    run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    row = _anomaly(db_session, "org")
    later = sync_run(db_session, org_id, PROVIDER, "cost_total", SPIKE_DAY, SEED_END)
    later.finished_at = row.detected_at + timedelta(minutes=5)
    db_session.commit()

    quality = anomaly_evidence(db_session, row).data_quality

    assert quality is not None and not quality.changed_since_detection
    assert {run.endpoint for run in quality.runs} >= {
        "cost_report",
        "allocation",
        "anomaly_detection",
    }


def test_day_breakdown_lists_every_row_with_its_own_history(
    db_session: Session, org_id: int
) -> None:
    def with_new_key(day: date) -> list[Line]:
        lines = spiked(day)
        if day == SPIKE_DAY:
            lines.append(("ws_a", "claude-haiku-3-5", "apikey_new", Decimal("30")))
        return lines

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, with_new_key)
    run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    row = _anomaly(db_session, "org")

    with counted_statements() as statements:
        evidence = anomaly_evidence(db_session, row)
    assert len(statements) <= QUERY_CEILING, f"{len(statements)} statements: {statements}"
    # The inventory is read once for the four breakdowns, not once per dimension.
    assert sum("FROM provider_api_keys" in s for s in statements) == 1

    assert [b.dimension for b in evidence.breakdowns] == [
        "api_key",
        "account",
        "model",
        "workspace",
    ]
    models = {r.label: r for r in evidence.breakdowns[2].rows}
    assert sum((r.amount or 0) for r in models.values()) == Decimal("570")
    opus = models["claude-opus-4-1"]
    # Aug 4-10 for opus: 5 x 60 and 2 x 12 -> 46.29 a day.
    assert opus.trailing_average is not None
    assert opus.trailing_average.quantize(Decimal("0.01")) == Decimal("46.29")
    assert opus.delta is not None and opus.delta.quantize(Decimal("0.01")) == Decimal("453.71")
    assert not opus.new
    haiku = models["claude-haiku-3-5"]
    assert haiku.new and haiku.trailing_average == 0 and haiku.delta == Decimal("30")
    keys = evidence.breakdowns[0].rows
    assert keys[0].label.startswith("apikey_a") and keys[0].delta is not None
    new_key = next(r for r in keys if r.label.startswith("apikey_new"))
    assert new_key.new
    # The seed derives tokens from the money at 30 USD per million on opus, so the row prices
    # back to that rate and the requests grow with the spend.
    assert opus.request_count > 0
    assert opus.cost_per_million is not None
    assert opus.cost_per_million.quantize(Decimal("1")) == Decimal("30")
    economics = evidence.unit_economics
    assert economics is not None and economics.sample_days == 8
    assert economics.day.amount == Decimal("570") and economics.baseline.amount == Decimal("100")
    assert economics.day.cost_per_million is not None
    quality = evidence.data_quality
    assert quality is not None
    assert (quality.cost_lines, quality.allocated_lines, quality.usage_lines) == (3, 3, 3)
    assert quality.unallocated_amount == 0 and not quality.changed_since_detection


def test_history_lists_the_other_anomalies_of_the_series(db_session: Session, org_id: int) -> None:
    second_day = SPIKE_DAY + timedelta(days=4)

    def two_spikes(day: date) -> list[Line]:
        lines = spiked(day)
        if day == second_day:
            lines[0] = ("ws_a", "claude-opus-4-1", "apikey_a", Decimal("600"))
        return lines

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, two_spikes)
    run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    first, second = db_session.scalars(
        select(SpendAnomaly).where(SpendAnomaly.series_kind == "org").order_by(SpendAnomaly.day)
    ).all()

    evidence = anomaly_evidence(db_session, second)

    assert [(h.id, h.day, h.actual) for h in evidence.history] == [
        (first.id, SPIKE_DAY, Decimal("540"))
    ]
    # The suppression check saw the first episode and the second deviated further: 588 USD
    # over a 20 USD weekend baseline against the first one's 440.
    suppression = evidence.checks[-1]
    assert suppression.passed and suppression.threshold == Decimal("440")


def test_a_drop_shows_its_own_checks_and_lower_bound(db_session: Session, org_id: int) -> None:
    quiet_day = date(2026, 8, 18)

    def stops(day: date) -> list[Line]:
        if day == quiet_day:
            return [("ws_b", "claude-sonnet-4", "apikey_b", Decimal("5"))]
        return spiked(day)

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, stops)
    run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    row = db_session.scalars(
        select(SpendAnomaly).where(SpendAnomaly.kind == "drop", SpendAnomaly.series_kind == "org")
    ).one()

    evidence = anomaly_evidence(db_session, row)

    assert [c.name for c in evidence.checks] == DROP_CHECK_NAMES
    assert all(c.passed for c in evidence.checks)
    detail = evidence.baseline
    assert detail is not None
    assert (detail.median, detail.lower) == (Decimal("100"), Decimal("80"))
    below = evidence.checks[0]
    assert (below.observed, below.threshold) == (Decimal("5"), Decimal("80"))
    complete = next(c for c in evidence.checks if c.name == "complete_day")
    assert complete.threshold == Decimal("2")


def test_a_new_principal_has_no_baseline_to_show(db_session: Session, org_id: int) -> None:
    first_seen = date(2026, 8, 15)

    def with_new_key(day: date) -> list[Line]:
        lines = spiked(day)
        if day >= first_seen:
            lines.append(("ws_a", "claude-opus-4-1", "apikey_new", Decimal("40")))
        return lines

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, with_new_key)
    run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    row = db_session.scalars(select(SpendAnomaly).where(SpendAnomaly.kind == "new_principal")).one()

    evidence = anomaly_evidence(db_session, row)

    # The rule fired because the series has no history, so the page shows the three
    # new-principal checks and no baseline card.
    assert evidence.baseline is None
    assert [c.name for c in evidence.checks] == NEW_PRINCIPAL_CHECK_NAMES
    assert all(c.passed for c in evidence.checks)
    share = next(c for c in evidence.checks if c.name == "new_principal_share")
    assert share.threshold is not None and share.observed == Decimal("40")
    assert evidence.unit_economics is None
