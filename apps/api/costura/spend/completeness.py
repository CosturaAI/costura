"""How far each account's billed spend is complete: the last day a succeeded cost sync
covered, and whether a later cost sync failed."""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import ProviderAccount, ProviderSyncRun
from costura.providers.registry import get_spec, resolve_scope
from costura.spend.anomalies import DETECTION_ENDPOINT
from costura.spend.scope import provider_clause


@dataclass(frozen=True)
class Completeness:
    # The last day every account in scope has a succeeded cost sync for; None without one.
    complete_through: date | None
    # True when an account's newest cost sync failed after its last success.
    stale: bool
    # The last day anomaly detection covered for every account; None before the first pass.
    detection_through: date | None = None


def completeness(session: Session, org_id: int, provider: str) -> Completeness:
    """Per account, the newest succeeded cost sync covers up to the day before its window
    end or the day before it finished, whichever is earlier: a provider's report for today
    is still filling. The scope's value is the earliest of its accounts. `stale` reads the
    newest run per account and window month, since each cycle syncs the current month and
    then the previous one: a failed current month is not hidden by the previous month's
    success. `detection_through` reads the anomaly detection runs the same way, so a skipped
    detection shows even while the totals stay current."""
    endpoints = {get_spec(p).cost_endpoint for p in resolve_scope(provider)}
    complete, stale = _coverage(session, org_id, provider, endpoints)
    detected, _ = _coverage(session, org_id, provider, {DETECTION_ENDPOINT})
    return Completeness(complete_through=complete, stale=stale, detection_through=detected)


def _coverage(
    session: Session, org_id: int, provider: str, endpoints: set[str]
) -> tuple[date | None, bool]:
    runs = session.scalars(
        select(ProviderSyncRun)
        .where(
            ProviderSyncRun.organization_id == org_id,
            provider_clause(ProviderSyncRun.provider, provider),
            ProviderSyncRun.endpoint.in_(endpoints),
            ProviderSyncRun.status.in_(("succeeded", "failed")),
        )
        .order_by(ProviderSyncRun.id)
    )
    disconnected = set(
        session.scalars(
            select(ProviderAccount.id).where(
                ProviderAccount.organization_id == org_id,
                ProviderAccount.disconnected_at.is_not(None),
            )
        )
    )
    through: dict[tuple[str, int | None], date] = {}
    last_status: dict[tuple[str, int | None, date], str] = {}
    for run in runs:
        if run.provider_account_id in disconnected:
            continue
        unit = (run.provider, run.provider_account_id)
        last_status[(*unit, run.window_start.date())] = run.status
        if run.status != "succeeded" or run.finished_at is None:
            continue
        covered = min(run.window_end.date(), run.finished_at.date()) - timedelta(days=1)
        if unit not in through or covered > through[unit]:
            through[unit] = covered
    stale = any(
        status == "failed" and (key[0], key[1]) in through for key, status in last_status.items()
    )
    return min(through.values(), default=None), stale
