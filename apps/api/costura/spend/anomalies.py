"""Daily spend anomalies: a series is off its own baseline and the noise filters agree.

Three rule families, each a deterministic comparison against a baseline computed
from the series' own history:

- `spike`: a day above the upper bound.
- `drop`: a day below the lower bound, on a day the provider has finished reporting.
- `new_principal`: a key or a login that spends a share of the organization's day while it
  still has less than `MIN_HISTORY_DAYS` of history, before any baseline can exist.

Consecutive days under the same rule are one episode with one frozen baseline, so a level
shift is reported once with a duration instead of once a day, and the shift never becomes the
new normal while it lasts. Everything is arithmetic on the daily series of `spend.daily`, so a
flag can be explained on screen with the numbers stored next to it.

The arithmetic lives in `anomaly_baseline` and `anomaly_rules`, the reads and writes of
`spend_anomalies` in `anomaly_store`; this module loads the series and runs one detection.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from costura import accounts
from costura.models import ProviderSyncRun
from costura.models.intelligence import (
    ANOMALY_SERIES_KINDS,
    ORG_SERIES_ID,
    PRINCIPAL_KINDS,
)
from costura.providers.http import stored_exception_text
from costura.spend.anomaly_rules import (
    HISTORY_DAYS,
    Candidate,
    DetectionResult,
    eligible_keys_by_day,
    evaluate_series,
    month_to_date,
    principal_days,
    root_causes,
)
from costura.spend.anomaly_store import (
    acknowledged_adjustments,
    child_candidates,
    load_calibration,
    prior_anomalies,
    store_detection,
)
from costura.spend.daily import (
    daily_amounts,
)
from costura.spend.ledger import costura_total
from costura.spend.window import Window

DETECTION_ENDPOINT = "anomaly_detection"


def run_detection(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    *,
    currency: str = "USD",
    today: date | None = None,
    account_id: int | None = None,
) -> DetectionResult:
    """Detect anomalies on every day of `window` that has data, for one account of the
    provider, and store them.

    Upserts by (series, first day of the episode) keeping the status of existing rows, and
    removes `open` rows in the window the pass no longer finds. `today` is the day the drop
    rule measures completeness against; it defaults to the current UTC day. Records a
    `provider_sync_runs` row with endpoint `anomaly_detection`. Without `account_id`, every
    account of the provider is evaluated in turn and the counts add up.
    """
    today = today or datetime.now(UTC).date()
    if account_id is None:
        ids = [a.id for a in accounts.list_accounts(session, org_id, provider)]
        if not ids:
            ids = [accounts.ensure_default_account(session, org_id, provider).id]
            session.commit()
        results = [
            run_detection(
                session, org_id, provider, window, currency=currency, today=today, account_id=i
            )
            for i in ids
        ]
        if len(results) == 1:
            return results[0]
        merged = DetectionResult(run_id=results[-1].run_id, window=window)
        for r in results:
            merged.found.extend(r.found)
            merged.evaluated_days = max(merged.evaluated_days, r.evaluated_days)
            merged.series_count += r.series_count
            merged.inserted += r.inserted
            merged.updated += r.updated
            merged.removed += r.removed
        return merged
    run = ProviderSyncRun(
        organization_id=org_id,
        provider=provider,
        provider_account_id=account_id,
        endpoint=DETECTION_ENDPOINT,
        window_start=window.start,
        window_end=window.end,
    )
    session.add(run)
    session.commit()
    result = DetectionResult(run_id=run.id, window=window)
    try:
        result.found = _detect(session, org_id, provider, window, result, today, account_id)
        _, billed_in = costura_total(session, org_id, provider, window, account_id)
        store_detection(
            session, org_id, provider, window, result, billed_in or currency, account_id
        )
        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        run.raw_results = result.evaluated_days
        run.rows_upserted = result.inserted + result.updated
        session.commit()
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.finished_at = datetime.now(UTC)
        run.error = stored_exception_text(exc)
        session.commit()
        raise
    return result


def _detect(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    result: DetectionResult,
    today: date,
    account_id: int,
) -> list[Candidate]:
    month_start = window.start.date()
    month_end = window.end.date()
    history_start = month_start - timedelta(days=HISTORY_DAYS)
    calibration = load_calibration(session, org_id)
    loaded = {
        kind: daily_amounts(
            session, org_id, provider, kind, history_start, month_end, account_id=account_id
        )
        for kind in ANOMALY_SERIES_KINDS
    }
    org_series = loaded["org"].get(ORG_SERIES_ID, {})
    days = sorted(
        d for d, amount in org_series.items() if month_start <= d < month_end and amount > 0
    )
    result.evaluated_days = len(days)
    if not days:
        return []
    principals = {
        (kind, series_id): series
        for kind in PRINCIPAL_KINDS
        for series_id, series in loaded[kind].items()
    }
    eligibility = eligible_keys_by_day(principals, days)
    prior = prior_anomalies(session, org_id, provider, account_id, history_start, month_start)
    adjustments = acknowledged_adjustments(
        session, org_id, provider, account_id, history_start, month_end
    )

    found: list[Candidate] = []
    for kind in ANOMALY_SERIES_KINDS:
        for series_id, series in sorted(loaded[kind].items()):
            evaluation_days = (
                principal_days(days, series, eligibility, (kind, series_id))
                if kind in PRINCIPAL_KINDS
                else days
            )
            if not evaluation_days:
                continue
            result.series_count += 1
            found.extend(
                evaluate_series(
                    kind,
                    series_id,
                    series,
                    evaluation_days,
                    org_series,
                    prior.get((kind, series_id), {}),
                    calibration=calibration,
                    adjustments=adjustments.get((kind, series_id), {}),
                    today=today,
                )
            )
    children = {
        id(candidate): child_candidates(
            session, org_id, provider, account_id, candidate, history_start, month_end
        )
        for candidate in found
    }
    for candidate in found:
        candidate.root_causes = root_causes(
            children[id(candidate)],
            candidate.day,
            falling=candidate.falling,
            sample_days=candidate.baseline.sample_days,
        )
        candidate.month_to_date = month_to_date(org_series, month_start, candidate.end_day)
    return found
