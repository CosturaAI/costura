"""Anomaly detection: baseline arithmetic, each filter of each rule family, episodes and the
stored result of a pass over a synthetic ten-week history."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from costura.models import (
    AnomalySettings,
    SpendAllocatedLine,
    SpendAnomaly,
    SpendCostLine,
)
from costura.models.intelligence import ORG_SERIES_ID
from costura.spend.anomalies import run_detection
from costura.spend.anomaly_baseline import THRESHOLDS, Baseline, baseline_detail, compute_baseline
from costura.spend.anomaly_rules import (
    EPISODE_MAX_DAYS,
    Candidate,
    eligible_keys_by_day,
    evaluate_series,
    rejection_reason,
)
from costura.spend.anomaly_store import purge_expired
from costura.spend.window import Window
from tests.seed import Line, oauth, seed_days

PROVIDER = "anthropic"
HISTORY_START = date(2026, 6, 1)
SEED_END = date(2026, 8, 21)
AUGUST = Window.for_month("2026-08")
SPIKE_DAY = date(2026, 8, 11)  # a Tuesday
WEEKDAY, WEEKEND = Decimal("100"), Decimal("20")
# Every day of the seeded history is settled, so the drop rule may read all of them.
TODAY = date(2026, 9, 1)


def steady(day: date, spike: Decimal | None = None) -> list[Line]:
    """Two workspaces, two models, two keys; 100 USD on weekdays, 20 on weekends."""
    scale = Decimal("0.2") if day.weekday() >= 5 else Decimal("1")
    a = Decimal("60") * scale
    if spike is not None and day == SPIKE_DAY:
        a = spike
    return [
        ("ws_a", "claude-opus-4-1", "apikey_a", a),
        ("ws_b", "claude-sonnet-4", "apikey_b", Decimal("40") * scale),
    ]


def spiked(day: date) -> list[Line]:
    """`steady` with workspace a at 500 USD on the spike day (organization total 540)."""
    return steady(day, Decimal("500"))


def series(values: dict[int, Decimal], anchor: date) -> dict[date, Decimal]:
    """A series keyed by offset in days before `anchor` (0 is the anchor itself)."""
    return {anchor - timedelta(days=offset): amount for offset, amount in values.items()}


def test_weekday_baseline_uses_the_same_weekday_and_a_relative_floor() -> None:
    anchor = SPIKE_DAY
    history = {
        offset: (WEEKEND if (anchor - timedelta(days=offset)).weekday() >= 5 else WEEKDAY)
        for offset in range(1, 71)
    }
    baseline = compute_baseline(series(history, anchor), anchor)

    # Every sample is 100, so the MAD is 0 and the 20% floor fixes the margin; with no MAD to
    # divide by, that margin is also the unit a deviation counts in.
    assert baseline == Baseline(
        expected=WEEKDAY,
        upper=Decimal("120"),
        method="weekday",
        samples=8,
        spread=Decimal("20"),
    )
    assert baseline.lower == Decimal("80")


def test_baseline_falls_back_to_trailing_days_for_a_young_series() -> None:
    anchor = SPIKE_DAY
    history = {offset: Decimal("10") + offset for offset in range(1, 15)}  # 11..24
    baseline = compute_baseline(series(history, anchor), anchor)

    assert baseline is not None
    assert baseline.method == "trailing"
    assert baseline.samples == 14
    assert baseline.expected == Decimal("17.5")
    # MAD of 11..24 around 17.5 is 3.5; 3 x 1.4826 x 3.5 = 15.5673 beats 20% and 5 USD.
    assert baseline.upper == Decimal("17.5") + Decimal("3") * Decimal("1.4826") * Decimal("3.5")


def test_retention_purges_episodes_by_their_end_day(db_session: Session, org_id: int) -> None:
    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, spiked)
    run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    before = db_session.scalar(
        select(SpendAnomaly.id).where(SpendAnomaly.organization_id == org_id).limit(1)
    )
    assert before is not None

    removed = purge_expired(db_session, org_id, today=TODAY + timedelta(days=100))

    assert removed > 0
    assert (
        db_session.scalar(
            select(SpendAnomaly.id).where(SpendAnomaly.organization_id == org_id).limit(1)
        )
        is None
    )


def test_key_eligibility_is_per_day_trailing_and_deterministic() -> None:
    first = date(2026, 8, 10)
    second = first + timedelta(days=1)
    by_key = {
        f"key-{index:02d}": {
            first - timedelta(days=1): Decimal(100 - index),
        }
        for index in range(25)
    }
    by_key["key-new"] = {
        first: Decimal("1000"),
        second + timedelta(days=1): Decimal("9999"),
    }
    by_key["key-extra"] = {first - timedelta(days=1): Decimal("200")}
    by_key["key-23"][first - timedelta(days=1)] = Decimal("1")
    by_key["key-24"][first - timedelta(days=1)] = Decimal("1")

    eligible = eligible_keys_by_day(by_key, [first, second])

    assert "key-new" not in eligible[first]
    assert "key-new" in eligible[second]
    assert "key-24" not in eligible[first]
    assert "key-23" in eligible[first]


def test_mad_spread_widens_the_bound_for_a_noisy_series() -> None:
    anchor = SPIKE_DAY
    noisy = {7 * k: Decimal(50 + 30 * (k % 2)) for k in range(1, 9)}  # alternates 80 and 50
    noisy.update({offset: Decimal("1") for offset in range(1, 57) if offset % 7})
    baseline = compute_baseline(series(noisy, anchor), anchor)

    assert baseline is not None
    assert baseline.expected == Decimal("65")
    assert baseline.upper == Decimal("65") + Decimal("3") * Decimal("1.4826") * Decimal("15")


def test_each_noise_filter_rejects_in_order() -> None:
    anchor = SPIKE_DAY
    flat = series({offset: Decimal("100") for offset in range(1, 71)}, anchor)
    baseline = Baseline(expected=Decimal("100"), upper=Decimal("120"), method="weekday", samples=8)

    def reason(
        actual: str,
        *,
        series: dict[date, Decimal] = flat,
        bound: Baseline = baseline,
        org_total: Decimal = Decimal("10000"),
        recent: dict[date, Decimal] | None = None,
    ) -> str | None:
        return rejection_reason(
            series,
            anchor,
            Decimal(actual),
            bound,
            org_total=org_total,
            recent_anomalies=recent or {},
        )

    assert reason("119") == "within upper bound"
    assert reason("140") is None
    tiny = Baseline(expected=Decimal("0.5"), upper=Decimal("1"), method="weekday", samples=8)
    assert reason("4", bound=tiny, org_total=Decimal("10")) == "below 5 USD"
    # 14 USD against an expected 6: above the bound, above 5 USD, but an 8 USD impact.
    small = Baseline(expected=Decimal("6"), upper=Decimal("11"), method="weekday", samples=8)
    low = series({offset: Decimal("6") for offset in range(1, 71)}, anchor)
    assert reason("14", series=low, bound=small, org_total=Decimal("100")) == "impact below 10 USD"
    assert reason("20", series=low, bound=small, org_total=Decimal("100")) is None
    assert reason("140", org_total=Decimal("100000")) == "below 0.5% of the organization total"
    # 140 is above the bound but not 20% above a 7-day average of 130.
    rising = series(
        {
            **{offset: Decimal("100") for offset in range(8, 71)},
            **{offset: Decimal("130") for offset in range(1, 8)},
        },
        anchor,
    )
    assert reason("140", series=rising) == "not 20% above the trailing 7-day average"
    # Previous day already at 150: the spike is not new.
    after_peak = series(
        {**{offset: Decimal("100") for offset in range(2, 71)}, 1: Decimal("150")}, anchor
    )
    assert reason("140", series=after_peak) == "not above the previous day"
    young = series({offset: Decimal("100") for offset in range(1, 11)}, anchor)
    assert reason("140", series=young) == "fewer than 12 days of history"
    # An episode 3 days ago whose worst day was 50 USD above expectation hides a 40 USD
    # impact; a 60 USD one deviates more and fires.
    three_days_ago = {anchor - timedelta(days=3): Decimal("50")}
    assert (
        reason("140", recent=three_days_ago)
        == "not above another anomaly in the same series within 7 days"
    )
    assert reason("160", recent=three_days_ago) is None
    assert reason("140", recent={anchor - timedelta(days=8): Decimal("50")}) is None


def test_sensitivity_widens_the_bound_and_raises_the_impact_floor() -> None:
    anchor = SPIKE_DAY
    history = {offset: Decimal("100") for offset in range(1, 71)}
    flat = series(history, anchor)

    bounds = {
        name: compute_baseline(flat, anchor, thresholds=thresholds)
        for name, thresholds in THRESHOLDS.items()
    }

    # A flat series has no MAD, so only the relative margin moves: 30%, 20%, 15%.
    assert [bounds[name].upper for name in ("low", "normal", "high")] == [  # type: ignore[union-attr]
        Decimal("130"),
        Decimal("120"),
        Decimal("115"),
    ]

    def reason(sensitivity: str, actual: str, *, history: dict[date, Decimal] = flat) -> str | None:
        bound = compute_baseline(history, anchor, thresholds=THRESHOLDS[sensitivity])
        assert bound is not None
        return rejection_reason(
            history,
            anchor,
            Decimal(actual),
            bound,
            org_total=Decimal("1000"),
            recent_anomalies={},
            thresholds=THRESHOLDS[sensitivity],
        )

    # 118 USD is inside the 120 USD bound of `normal` and above the 115 USD one of `high`; the
    # trailing-week gate moves with the bound, so it does not swallow the difference.
    assert reason("high", "118") is None
    assert reason("normal", "118") == "within upper bound"
    # 32 USD on a 10 USD series clears the 10 USD impact floor of `normal`, not the 25 of `low`.
    ten = series({offset: Decimal("10") for offset in range(1, 71)}, anchor)
    assert reason("low", "32", history=ten) == "impact below 25 USD"
    assert reason("normal", "32", history=ten) is None


def test_an_intermittent_series_is_measured_on_the_days_it_runs() -> None:
    """A job that runs every third day is zero on six of its eight weekday samples, so the
    median sits at zero and the upper bound at the 5 USD absolute margin: every day the job
    ran looked like an anomaly. The active-day baseline reads the days it did run."""
    anchor = date(2026, 8, 20)
    history = {
        offset: (Decimal("300") if offset % 3 == 0 else Decimal("0")) for offset in range(1, 71)
    }
    run = series(history, anchor)
    detail = baseline_detail(run, anchor)

    assert detail is not None
    assert detail.method == "active_days"
    assert detail.median == Decimal("300")
    assert detail.upper == Decimal("360")

    def reason(actual: str) -> str | None:
        return rejection_reason(
            run,
            anchor,
            Decimal(actual),
            detail.baseline,  # type: ignore[union-attr]
            org_total=Decimal("1000"),
            recent_anomalies={},
        )

    assert reason("300") == "within upper bound"
    assert reason("920") is None


def test_a_growing_series_is_expected_to_keep_growing() -> None:
    """Ten weeks of 10% weekly growth: the samples are carried along their own slope, so the
    expected amount sits near the current level instead of four weeks behind it."""
    anchor = SPIKE_DAY
    history = {
        offset: (Decimal("100") * Decimal("1.1") ** (Decimal(-offset) / 7)).quantize(
            Decimal("0.01")
        )
        for offset in range(1, 71)
    }
    detail = baseline_detail(series(history, anchor), anchor)

    assert detail is not None
    assert detail.trend_per_week > Decimal("5")
    # Without the shift the median is the sample four weeks back, 68.30 USD; with it the
    # baseline expects this week's level, which is what makes a stall a drop.
    assert detail.median > Decimal("80")
    assert detail.upper > Decimal("100")
    assert detail.lower > Decimal("70")


def test_a_larger_spike_within_seven_days_fires_and_a_smaller_one_does_not(
    db_session: Session, org_id: int
) -> None:
    second_day = SPIKE_DAY + timedelta(days=4)  # a Saturday

    def two_spikes(day: date) -> list[Line]:
        lines = spiked(day)
        if day == second_day:
            lines[0] = ("ws_a", "claude-opus-4-1", "apikey_a", Decimal("600"))
        return lines

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, two_spikes)
    result = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    org_days = sorted(c.day for c in result.found if c.series_kind == "org")
    assert org_days == [SPIKE_DAY, second_day]

    for table in (SpendCostLine, SpendAllocatedLine, SpendAnomaly):
        db_session.execute(delete(table))
    db_session.commit()

    def smaller_second(day: date) -> list[Line]:
        lines = spiked(day)
        if day == second_day:
            lines[0] = ("ws_a", "claude-opus-4-1", "apikey_a", Decimal("400"))
        return lines

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, smaller_second)
    result = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    assert sorted(c.day for c in result.found if c.series_kind == "org") == [SPIKE_DAY]


def test_spike_is_detected_on_the_org_total_and_the_principal_only(
    db_session: Session, org_id: int
) -> None:
    """One spike, two rows: the organization total and the key that spent it. The workspace
    and the model are root causes, not anomalies of their own."""
    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, spiked)

    result = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    assert result.evaluated_days == 20
    assert result.inserted == 2 and result.updated == 0 and result.removed == 0
    rows = {
        (row.series_kind, row.series_id): row
        for row in db_session.scalars(select(SpendAnomaly).order_by(SpendAnomaly.id))
    }
    assert set(rows) == {("org", "__org__"), ("api_key", "apikey_a")}
    org = rows[("org", "__org__")]
    assert org.day == SPIKE_DAY
    assert (org.actual, org.expected, org.upper_bound) == (
        Decimal("540"),
        Decimal("100"),
        Decimal("120"),
    )
    assert (org.baseline_method, org.baseline_samples) == ("weekday", 8)
    # One day off the bound: a closed one-day episode, with the totals equal to that day.
    assert (org.kind, org.end_day, org.duration_days, org.ongoing) == (
        "spike",
        SPIKE_DAY,
        1,
        False,
    )
    assert org.lower_bound == Decimal("80")
    assert (org.total_actual, org.total_expected) == (Decimal("540"), Decimal("100"))
    assert (org.total_impact, org.max_impact) == (Decimal("440"), Decimal("440"))
    # 440 USD over a 20 USD margin, the spread of a series whose samples are identical.
    assert org.deviation == Decimal("22.00")
    assert org.severity == "high"
    assert org.impact == Decimal("440")
    assert org.impact_percent == Decimal("440.00")
    # 440 over the 1220 USD spent from Aug 1 to the spike day (4 x 20 + 6 x 100 + 540).
    assert org.impact_share == Decimal("0.360656")
    assert org.status == "open"
    assert org.currency == "USD"
    # Contributors measured on the anomaly's own baseline days: the key and its model tie on
    # delta, so the kind name orders them; the workspace is not a root cause kind. Each one
    # carries the whole change of its kind, so its delta is the impact and its share is 1.
    assert [(c["kind"], c["id"]) for c in org.root_causes[:2]] == [
        ("api_key", "apikey_a"),
        ("model", "claude-opus-4-1"),
    ]
    assert Decimal(str(org.root_causes[0]["delta"])) == org.impact
    assert [c["share"] for c in org.root_causes[:2]] == ["1.0000", "1.0000"]
    assert all(c["kind"] != "workspace" for c in org.root_causes)
    key = rows[("api_key", "apikey_a")]
    assert [(c["kind"], c["id"]) for c in key.root_causes] == [("model", "claude-opus-4-1")]


def test_oauth_usage_is_an_account_series_of_its_own(db_session: Session, org_id: int) -> None:
    """A Claude Code login spikes: the `account` row names the user, the key keeps quiet,
    and the organization row points at the account first."""

    def with_login(day: date) -> list[Line]:
        scale = Decimal("0.2") if day.weekday() >= 5 else Decimal("1")
        login = Decimal("500") if day == SPIKE_DAY else Decimal("30") * scale
        return [
            ("ws_a", "claude-opus-4-1", "apikey_a", Decimal("30") * scale),
            ("ws_a", "claude-opus-4-1", oauth("user_ana"), login),
            ("ws_b", "claude-sonnet-4", "apikey_b", Decimal("40") * scale),
        ]

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, with_login)
    result = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    assert {(c.series_kind, c.series_id) for c in result.found} == {
        ("org", "__org__"),
        ("account", "user_ana"),
    }
    account = next(c for c in result.found if c.series_kind == "account")
    assert (account.actual, account.baseline.expected) == (Decimal("500"), Decimal("30"))
    assert [(c["kind"], c["id"]) for c in account.root_causes] == [("model", "claude-opus-4-1")]
    org = next(c for c in result.found if c.series_kind == "org")
    # On the anomaly's baseline days the login and its model rise by the same 470, so the kind
    # name orders them and the login, the principal, comes first.
    assert [(c["kind"], c["id"]) for c in org.root_causes[:2]] == [
        ("account", "user_ana"),
        ("model", "claude-opus-4-1"),
    ]


def test_eligibility_ranks_keys_and_accounts_together(db_session: Session, org_id: int) -> None:
    """26 principals, one of them a login: the smallest key drops out of the top 25 and the
    login stays; a spike on the dropped key is not evaluated."""

    def crowd(day: date) -> list[Line]:
        lines: list[Line] = [
            ("ws_a", "claude-opus-4-1", f"apikey_{index:02d}", Decimal(100 - index))
            for index in range(25)
        ]
        lines.append(("ws_a", "claude-opus-4-1", oauth("user_ana"), Decimal("90")))
        smallest = Decimal("500") if day == SPIKE_DAY else Decimal("1")
        lines.append(("ws_a", "claude-opus-4-1", "apikey_small", smallest))
        return lines

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, crowd)
    result = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    kinds = {(c.series_kind, c.series_id) for c in result.found}
    assert ("api_key", "apikey_small") not in kinds
    assert ("org", "__org__") in kinds
    # 27 principals seen, 25 evaluated per day plus the organization total.
    assert result.series_count == 26


def test_percent_is_null_when_the_baseline_is_below_one_dollar(
    db_session: Session, org_id: int
) -> None:
    def rare(day: date) -> list[Line]:
        lines = steady(day)
        amount = Decimal("60") if day == SPIKE_DAY else Decimal("0.05")
        return [*lines, ("ws_r", "claude-opus-4-1", "apikey_r", amount)]

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, rare)
    run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    row = db_session.scalar(select(SpendAnomaly).where(SpendAnomaly.series_id == "apikey_r"))
    assert row is not None
    assert row.expected == Decimal("0.05")
    assert row.impact_percent is None
    assert row.impact_share is not None and Decimal("0") < row.impact_share <= Decimal("1")


def test_impact_share_is_null_without_month_to_date_spend() -> None:
    from costura.spend.anomaly_rules import Candidate, month_to_date

    baseline = Baseline(Decimal("10"), Decimal("20"), "weekday", 8)
    candidate = Candidate("org", "org", SPIKE_DAY, Decimal("50"), baseline)
    assert candidate.impact_share is None
    # The previous month's spend does not count.
    org_series = {SPIKE_DAY: Decimal("50"), date(2026, 7, 31): Decimal("900")}
    candidate.month_to_date = month_to_date(org_series, date(2026, 8, 1), SPIKE_DAY)
    assert candidate.month_to_date == Decimal("50")
    assert candidate.impact_share == Decimal("0.8")


def test_weekend_dips_and_a_steady_trend_do_not_fire(db_session: Session, org_id: int) -> None:
    def trend(day: date) -> list[Line]:
        growth = Decimal("1.02") ** (day - HISTORY_START).days
        amount = (Decimal("50") * growth).quantize(Decimal("0.01"))
        return [("ws_t", "claude-opus-4-1", "apikey_t", amount)]

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, lambda d: steady(d) + trend(d))

    result = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    assert result.found == []
    assert db_session.scalar(select(SpendAnomaly)) is None


def test_rerun_is_idempotent_keeps_acknowledgements_and_drops_vanished_spikes(
    db_session: Session, org_id: int
) -> None:
    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, spiked)
    run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    org_row = db_session.scalar(select(SpendAnomaly).where(SpendAnomaly.series_kind == "org"))
    assert org_row is not None
    org_row.status = "acknowledged"
    db_session.commit()

    second = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    assert (second.inserted, second.updated, second.removed) == (0, 2, 0)
    db_session.refresh(org_row)
    assert org_row.status == "acknowledged"

    # The provider re-reports the day without the spike: open rows go, the acknowledged stays.
    for table in (SpendCostLine, SpendAllocatedLine):
        db_session.execute(delete(table))
    db_session.commit()
    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, steady)
    third = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    assert (third.inserted, third.updated, third.removed) == (0, 0, 1)
    remaining = list(db_session.scalars(select(SpendAnomaly)))
    assert [(r.series_kind, r.status) for r in remaining] == [("org", "acknowledged")]


def test_a_level_shift_is_one_ongoing_episode(db_session: Session, org_id: int) -> None:
    """Spend doubles on a Tuesday and stays there: one row with a five-day run, the totals of
    the whole run, and the baseline of the first day held throughout."""
    last_day = SPIKE_DAY + timedelta(days=4)

    def shift(day: date) -> list[Line]:
        lines = steady(day)
        if SPIKE_DAY <= day <= last_day:
            lines[0] = ("ws_a", "claude-opus-4-1", "apikey_a", Decimal("260"))
        return lines

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, last_day + timedelta(days=1), shift)
    run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    org = db_session.scalar(select(SpendAnomaly).where(SpendAnomaly.series_kind == "org"))
    assert org is not None
    assert (org.day, org.end_day, org.duration_days) == (SPIKE_DAY, last_day, 5)
    # The run ends on the last day with data, so the episode is still open in the data.
    assert org.ongoing is True
    assert (org.expected, org.upper_bound) == (Decimal("100"), Decimal("120"))
    assert org.actual == Decimal("300")  # 260 plus the 40 of workspace b
    assert org.impact == Decimal("200")
    # Four weekdays at 300 and one Saturday at 268 (260 plus the weekend-scaled 8 of b), every
    # one of them measured against the same 100 USD expectation.
    assert org.total_actual == Decimal("300") * 4 + Decimal("268")
    assert org.total_expected == Decimal("500")
    assert org.total_impact == org.total_actual - org.total_expected
    assert org.max_impact == Decimal("200")
    assert org.severity == "high"


def test_a_return_to_normal_closes_the_episode(db_session: Session, org_id: int) -> None:
    """Two days off the bound, then a normal day: the episode covers two days and is closed,
    and the normal days after it are not re-flagged."""
    second_day = SPIKE_DAY + timedelta(days=1)

    def two_days(day: date) -> list[Line]:
        lines = steady(day)
        if day in (SPIKE_DAY, second_day):
            lines[0] = ("ws_a", "claude-opus-4-1", "apikey_a", Decimal("300"))
        return lines

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, two_days)
    result = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    org = [c for c in result.found if c.series_kind == "org"]
    assert len(org) == 1
    assert (org[0].day, org[0].end_day, org[0].duration_days, org[0].ongoing) == (
        SPIKE_DAY,
        second_day,
        2,
        False,
    )


def test_an_episode_stops_at_the_month_and_the_next_month_accepts_the_level(
    db_session: Session, org_id: int
) -> None:
    """A level shift on July 20 is one episode to the end of the month; August opens no
    episode of its own, because by then the trailing week is the new level."""
    shift_day = date(2026, 7, 20)

    def shift(day: date) -> list[Line]:
        lines = steady(day)
        if day >= shift_day:
            lines[0] = ("ws_a", "claude-opus-4-1", "apikey_a", Decimal("300"))
        return lines

    seed_days(db_session, org_id, PROVIDER, date(2026, 5, 1), date(2026, 9, 1), shift)
    july = run_detection(db_session, org_id, PROVIDER, Window.for_month("2026-07"), today=TODAY)
    august = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    july_org = [c for c in july.found if c.series_kind == "org"]
    assert len(july_org) == 1
    # The detection window is the month, so the episode ends with July and the row for it
    # says so: 12 days, not ongoing.
    assert (july_org[0].day, july_org[0].end_day) == (shift_day, date(2026, 7, 31))
    assert (july_org[0].duration_days, july_org[0].ongoing) == (12, True)
    assert [c.day for c in august.found if c.series_kind == "org"] == []


def test_an_episode_stops_after_the_maximum_run() -> None:
    """Twice the usual spend every day for two months: the episode covers 28 days and stops,
    because a level that holds that long is the level."""
    start = date(2026, 6, 1)
    history = {start + timedelta(days=k): Decimal("100") for k in range(92)}  # June to August
    days = sorted(day for day in history if day >= date(2026, 8, 1))
    for day in days:
        history[day] = Decimal("300")

    episodes = evaluate_series("org", ORG_SERIES_ID, history, days, history, {}, today=TODAY)

    assert len(episodes) == 1
    assert (episodes[0].day, episodes[0].duration_days) == (date(2026, 8, 1), EPISODE_MAX_DAYS)
    assert episodes[0].ongoing is False


def test_a_drop_fires_on_a_settled_day_and_not_before(db_session: Session, org_id: int) -> None:
    """The organization spends every day, then one workspace stops: the day is below the
    lower bound, and the rule waits for the provider to finish reporting it."""
    quiet_day = date(2026, 8, 18)  # a Tuesday

    def stops(day: date) -> list[Line]:
        if day == quiet_day:
            return [("ws_b", "claude-sonnet-4", "apikey_b", Decimal("5"))]
        return steady(day)

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, stops)

    early = run_detection(db_session, org_id, PROVIDER, AUGUST, today=quiet_day + timedelta(days=1))
    assert [c.day for c in early.found if c.kind == "drop"] == []

    settled = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    drops = [c for c in settled.found if c.kind == "drop"]
    # The organization fell, and so did each of the two keys behind it.
    assert {(c.series_kind, c.series_id) for c in drops} == {
        ("org", "__org__"),
        ("api_key", "apikey_a"),
        ("api_key", "apikey_b"),
    }
    assert {c.day for c in drops} == {quiet_day}
    row = db_session.scalar(
        select(SpendAnomaly).where(SpendAnomaly.kind == "drop", SpendAnomaly.series_kind == "org")
    )
    assert row is not None
    assert (row.actual, row.expected) == (Decimal("5"), Decimal("100"))
    assert row.lower_bound == Decimal("80")
    # The impact of a drop is the money the day did not spend, a magnitude like any other.
    assert row.impact == Decimal("95")
    assert row.severity == "medium"
    # The contributors are the ones that fell furthest, not the ones that grew.
    assert [c["kind"] for c in row.root_causes]
    assert all(Decimal(str(c["delta"])) < 0 for c in row.root_causes)


def test_drops_are_off_when_the_organization_turns_them_off(
    db_session: Session, org_id: int
) -> None:
    quiet_day = date(2026, 8, 18)

    def stops(day: date) -> list[Line]:
        if day == quiet_day:
            return [("ws_b", "claude-sonnet-4", "apikey_b", Decimal("5"))]
        return steady(day)

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, stops)
    db_session.add(AnomalySettings(organization_id=org_id, detect_drops=False))
    db_session.commit()

    result = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    assert [c.kind for c in result.found] == []


def test_a_new_key_that_spends_a_share_of_the_day_is_flagged_once(
    db_session: Session, org_id: int
) -> None:
    """A key created three days ago already carries a fifth of the organization's day: no
    baseline exists yet, so the spike rule cannot see it and the new-principal rule does."""
    first_seen = date(2026, 8, 15)

    def with_new_key(day: date) -> list[Line]:
        lines = steady(day)
        if day >= first_seen:
            lines.append(("ws_a", "claude-opus-4-1", "apikey_new", Decimal("40")))
        return lines

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, with_new_key)
    result = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    new = [c for c in result.found if c.kind == "new_principal"]
    assert [(c.series_kind, c.series_id, c.day) for c in new] == [
        ("api_key", "apikey_new", first_seen)
    ]
    row = db_session.scalar(select(SpendAnomaly).where(SpendAnomaly.kind == "new_principal"))
    assert row is not None
    # Every day it ran is the same episode, from the first to the last day with data.
    assert (row.day, row.end_day, row.duration_days) == (first_seen, date(2026, 8, 20), 6)
    assert (row.expected, row.baseline_method) == (Decimal("0"), "new_series")
    assert row.lower_bound is None
    assert row.deviation is None
    assert row.impact == Decimal("40")
    assert row.impact_percent is None
    # 240 USD over the run, and no baseline spread to deviate from, so the money rule decides.
    assert row.severity == "medium"


def test_new_principals_are_off_when_the_organization_turns_them_off(
    db_session: Session, org_id: int
) -> None:
    first_seen = date(2026, 8, 15)

    def with_new_key(day: date) -> list[Line]:
        lines = steady(day)
        if day >= first_seen:
            lines.append(("ws_a", "claude-opus-4-1", "apikey_new", Decimal("40")))
        return lines

    seed_days(db_session, org_id, PROVIDER, HISTORY_START, SEED_END, with_new_key)
    db_session.add(AnomalySettings(organization_id=org_id, detect_new_principals=False))
    db_session.commit()

    result = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    assert [c.kind for c in result.found if c.kind == "new_principal"] == []


def test_severity_ranks_a_small_spike_on_a_flat_series_above_a_big_one_on_a_noisy_series(
    db_session: Session, org_id: int
) -> None:
    """The AWS rule: severity is how abnormal the day is, not only how much money it moved.
    A 60 USD day on a series that never left 10 USD outranks the same money on a series that
    swings between 10 and 200."""
    anchor = SPIKE_DAY
    flat = series({offset: Decimal("10") for offset in range(1, 71)}, anchor)
    noisy = series({7 * k: Decimal(10 + 190 * (k % 2)) for k in range(1, 9)}, anchor)

    steady_bound = compute_baseline(flat, anchor)
    noisy_bound = compute_baseline(noisy, anchor)
    assert steady_bound is not None and noisy_bound is not None

    small = Candidate("api_key", "flat", anchor, Decimal("70"), steady_bound)
    big = Candidate("api_key", "noisy", anchor, Decimal("700"), noisy_bound)

    assert small.deviation == Decimal("12.00")  # 60 USD over the 5 USD absolute margin
    assert small.severity == "high"
    assert big.deviation is not None and big.deviation < Decimal("5")
    assert big.severity == "high"  # 595 USD is high on the money rule alone
    medium = Candidate("api_key", "noisy", anchor, Decimal("400"), noisy_bound)
    assert medium.severity == "medium"


def test_an_acknowledged_day_is_read_at_its_expected_amount() -> None:
    """Half the weekday samples sit inside an episode: their spread widens the bound by an
    order of magnitude. Once the user confirms the episode, the samples read the expectation
    the detector had for those days, and the bound goes back to the normal level."""
    anchor = SPIKE_DAY
    history = {offset: Decimal("100") for offset in range(1, 71)}
    episode = [anchor - timedelta(days=7 * k) for k in (2, 3, 4, 5)]
    for day in episode:
        history[(anchor - day).days] = Decimal("540")
    spiky = series(history, anchor)

    raw = baseline_detail(spiky, anchor)
    assert raw is not None
    assert raw.median == Decimal("320")
    assert raw.upper > Decimal("1000")

    confirmed = baseline_detail(spiky, anchor, adjustments=dict.fromkeys(episode, Decimal("100")))
    assert confirmed is not None
    assert (confirmed.median, confirmed.upper) == (Decimal("100"), Decimal("120"))
    assert confirmed.sample_amounts != confirmed.sample_values


def test_a_confirmed_level_shift_does_not_hide_the_next_one(
    db_session: Session, org_id: int
) -> None:
    """A 28-day episode in July is acknowledged; four of the weekday samples of August 11 fall
    inside it. Before the acknowledgement the spread of those samples swallows a 540 USD day;
    after it, the same day is an anomaly."""
    shift_start = date(2026, 7, 1)
    shift_end = date(2026, 7, 28)

    def shift(day: date) -> list[Line]:
        lines = steady(day)
        if shift_start <= day <= shift_end or day == SPIKE_DAY:
            lines[0] = ("ws_a", "claude-opus-4-1", "apikey_a", Decimal("500"))
        return lines

    seed_days(db_session, org_id, PROVIDER, date(2026, 5, 1), SEED_END, shift)
    july = run_detection(db_session, org_id, PROVIDER, Window.for_month("2026-07"), today=TODAY)
    episode = next(c for c in july.found if c.series_kind == "org")
    assert (episode.day, episode.duration_days) == (shift_start, EPISODE_MAX_DAYS)

    before = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    # The July level sits in the samples of every Tuesday in August: it hides the spike on
    # the 11th and turns the normal 18th into a drop below a 432 USD lower bound.
    assert [(c.day, c.kind) for c in before.found if c.series_kind == "org"] == [
        (date(2026, 8, 18), "drop")
    ]

    row = db_session.scalar(
        select(SpendAnomaly).where(
            SpendAnomaly.series_kind == "org", SpendAnomaly.day == shift_start
        )
    )
    assert row is not None
    row.status = "acknowledged"
    db_session.commit()

    after = run_detection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    found = [c for c in after.found if c.series_kind == "org"]
    assert [(c.day, c.kind, c.baseline.expected) for c in found] == [
        (SPIKE_DAY, "spike", Decimal("100"))
    ]


def test_root_cause_shares_split_the_change_of_their_kind() -> None:
    from costura.spend.anomaly_rules import root_causes

    day = date(2026, 8, 11)
    samples = [day - timedelta(days=7 * k) for k in range(1, 5)]

    def series(base: str, on_day: str) -> dict[date, Decimal]:
        return {**{d: Decimal(base) for d in samples}, day: Decimal(on_day)}

    split = root_causes(
        {"api_key": {"a": series("100", "400"), "b": series("50", "150")}},
        day,
        sample_days=samples,
    )
    assert [(c["id"], c["delta"], c["share"]) for c in split] == [
        ("a", "300.00000000", "0.7500"),
        ("b", "100.00000000", "0.2500"),
    ]

    offset = root_causes(
        {"api_key": {"a": series("100", "500"), "b": series("200", "100")}},
        day,
        sample_days=samples,
    )
    assert [(c["id"], c["share"]) for c in offset] == [("a", "1.3333")]
