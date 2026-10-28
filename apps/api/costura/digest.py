"""A scheduled summary posted to the organization's webhook: the month so far, its change,
the month-end projection and what needs a person. Weekly on Mondays or monthly on the 2nd,
once per period, off by default."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from costura.config import Settings
from costura.delivery import Post, http_post, send_text, signal_path, views, web_link
from costura.models import Organization, WebhookDestination
from costura.spend.projection import stored_projections
from costura.spend.scope import ALL
from costura.spend.signals import collect_signals, org_thresholds
from costura.spend.summary import summary

TOP_SIGNALS = 3
CENT = Decimal("0.01")
RETRY_AFTER = timedelta(minutes=30)
_last_failure: dict[int, datetime] = {}


def _usd(value: Decimal) -> str:
    return f"{value.quantize(CENT):,.2f} USD"


def due(row: WebhookDestination, today: date) -> bool:
    """Mondays for weekly, the 2nd for monthly, and not already posted that day."""
    if row.digest == "weekly":
        on_day = today.weekday() == 0
    elif row.digest == "monthly":
        on_day = today.day == 2
    else:
        return False
    last = row.last_digest_on
    return on_day and (last is None or last < today)


def digest_text(session: Session, settings: Settings, org: Organization, today: date) -> str:
    month = f"{today.year}-{today.month:02d}"
    if today.day <= 2:
        previous = date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)
        month = f"{previous.year}-{previous.month:02d}"
    found = summary(session, org_id=org.id, provider=ALL, month=month, today=today)
    lines = [f"*Costura digest for {org.name}*, {month}"]
    change = (
        f", {found.change_percent:+.1f}% against the same days before"
        if found.change_percent is not None
        else ""
    )
    lines.append(f"Spend so far: {_usd(found.total)}{change}.")
    rows = stored_projections(session, org.id, ALL, month, "org")
    if rows and found.is_current_month:
        projected = sum((Decimal(r.projected_total) for r in rows), Decimal("0"))
        lines.append(f"Projected month end: {_usd(projected)}.")
    if found.complete_through is not None and found.data_stale:
        lines.append("The last import failed; figures stop at the last complete day.")
    signals = collect_signals(
        session, org.id, ALL, today=today, thresholds=org_thresholds(session, org.id)
    )
    if signals:
        seen = views(session, org.id)
        lines.append(f"Needs a person: {len(signals)} open, most money first:")
        for signal in signals[:TOP_SIGNALS]:
            label = seen.signals.label(signal)
            link = web_link(settings, org.slug, signal_path(signal))
            lines.append(
                f"- {signal.kind.replace('_', ' ')}: {label}, "
                f"{_usd(signal.dollars_at_risk)} <{link}|open>"
            )
    else:
        lines.append("Nothing needs a person.")
    lines.append(f"<{web_link(settings, org.slug, '/overview')}|Open the Overview>")
    return "\n".join(lines)


def post_digest(
    session: Session,
    settings: Settings,
    row: WebhookDestination,
    *,
    today: date | None = None,
    post: Post | None = None,
) -> str | None:
    """Post the digest when it is due; None when it was posted or not due, else the error.
    A failed post waits `RETRY_AFTER` before the next try that day. `X-Costura-Delivery` is
    `digest-<day>`, the same for every try of one digest, so a receiver can drop a repeat."""
    now = datetime.now(UTC)
    today = today or now.date()
    org = session.get(Organization, row.organization_id)
    if org is None or not due(row, today):
        return None
    failed_at = _last_failure.get(row.organization_id)
    if failed_at is not None and now - failed_at < RETRY_AFTER:
        return None
    error = send_text(
        settings,
        row,
        digest_text(session, settings, org, today),
        f"digest-{today.isoformat()}",
        post or http_post,
    )
    if error is None:
        row.last_digest_on = today
        _last_failure.pop(row.organization_id, None)
    else:
        _last_failure[row.organization_id] = now
    session.flush()
    return error
