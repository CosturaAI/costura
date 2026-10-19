"""Deliver signals to an organization's Slack-compatible webhook.

The worker calls `deliver_all` once a minute. Each pass records every current signal of an
organization with a destination as a `webhook_deliveries` row (once per signal), then posts
the rows that are due. A failed post is retried with backoff until `MAX_ATTEMPTS`; a signal
that closed before its turn is skipped. Nothing leaves the stack unless the operator lists
the destination's host in `COSTURA_WEBHOOK_HOSTS`.
"""

import hashlib
import hmac
import json
import logging
import secrets as token_source
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from costura import secrets
from costura.api.presenters.anomalies import AnomalyView, anomaly_view, explanation_of
from costura.api.presenters.signals import SignalView, detail_of
from costura.config import Settings
from costura.errors import DomainError, InvalidInput, NotFound
from costura.models import Organization, WebhookDelivery, WebhookDestination
from costura.spend.inbox import read_key
from costura.spend.scope import ALL
from costura.spend.signals import Signal, collect_signals, org_thresholds

log = logging.getLogger(__name__)

CENT = Decimal("0.01")
MAX_URL_LENGTH = 2048
NOT_POSTED = frozenset({"webhook_failing"})
MAX_ATTEMPTS = 5
BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2))
BATCH = 20
TIMEOUT_SECONDS = 10.0
SIGNATURE_VERSION = "v1"
KIND_TITLES = {
    "anomaly": "Anomaly",
    "budget": "Budget",
    "sync_stale": "Import stopped",
    "model_retiring": "Model retiring",
    "near_limit": "Near a provider limit",
    "idle_seat": "Idle paid seat",
    "seat_no_limit": "Member without a limit",
    "unit_cost_up": "Cost per token up",
    "no_owner": "Key without an owner",
    "no_limit": "Key without a limit",
    "owner_left": "Key whose owner left",
    "idle_active": "Idle key still active",
    "new_key": "New key",
}

Post = Callable[[str, bytes, dict[str, str]], int]


class DeliveryOff(DomainError):
    status = 409
    code = "webhooks_off"

    def __init__(self) -> None:
        super().__init__(
            "outbound webhooks are off on this stack; the operator lists allowed hosts in "
            "COSTURA_WEBHOOK_HOSTS"
        )


@dataclass(frozen=True)
class Saved:
    destination: WebhookDestination
    signing_secret: str


def check_url(settings: Settings, url: str) -> str:
    """The host of an HTTPS URL on the allowed list, or InvalidInput. The message never
    repeats the URL: its path is the credential."""
    hosts = settings.webhook_hosts
    if not hosts:
        raise DeliveryOff()
    cleaned = url.strip()
    if len(cleaned) > MAX_URL_LENGTH:
        raise InvalidInput(f"the webhook URL is longer than {MAX_URL_LENGTH} characters")
    parts = urlsplit(cleaned)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or not host:
        raise InvalidInput("the webhook URL must start with https://")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise InvalidInput("the webhook URL cannot carry a user, a password or a port")
    if host not in hosts:
        raise InvalidInput(
            f"{host} is not an allowed webhook host; allowed: {', '.join(sorted(hosts))}"
        )
    return host


def destination(session: Session, org_id: int) -> WebhookDestination | None:
    return session.get(WebhookDestination, org_id)


def save_destination(session: Session, settings: Settings, org_id: int, url: str) -> Saved:
    """Store the URL and a new signing secret, both encrypted. The first save records the
    signals open at that moment as skipped, so only what appears afterwards is posted."""
    host = check_url(settings, url)
    signing_secret = token_source.token_urlsafe(32)
    row = destination(session, org_id)
    first = row is None
    if row is None:
        row = WebhookDestination(organization_id=org_id)
        session.add(row)
    row.url_ciphertext = secrets.encrypt_bound(
        settings, secrets.webhook_context(org_id, "url"), url.strip()
    )
    row.url_host = host
    row.secret_ciphertext = secrets.encrypt_bound(
        settings, secrets.webhook_context(org_id, "secret"), signing_secret
    )
    row.key_version = secrets.KEY_VERSION
    session.flush()
    if first:
        record_signals(session, org_id, status="skipped")
    return Saved(destination=row, signing_secret=signing_secret)


def remove_destination(session: Session, org_id: int) -> None:
    """Forget the destination and every delivery row; saving one again starts over."""
    session.execute(delete(WebhookDelivery).where(WebhookDelivery.organization_id == org_id))
    session.execute(delete(WebhookDestination).where(WebhookDestination.organization_id == org_id))
    session.flush()


def recent_deliveries(session: Session, org_id: int, limit: int = 20) -> list[WebhookDelivery]:
    return list(
        session.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.organization_id == org_id, WebhookDelivery.status != "skipped")
            .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
            .limit(limit)
        )
    )


def current_signals(session: Session, org_id: int) -> list[Signal]:
    return collect_signals(session, org_id, ALL, thresholds=org_thresholds(session, org_id))


def record_signals(
    session: Session, org_id: int, *, status: str = "pending", found: list[Signal] | None = None
) -> None:
    keys = {read_key(s) for s in (current_signals(session, org_id) if found is None else found)}
    if keys:
        session.execute(
            pg_insert(WebhookDelivery)
            .values(
                [
                    {
                        "organization_id": org_id,
                        "kind": kind,
                        "provider": provider,
                        "reference": reference,
                        "status": status,
                    }
                    for kind, provider, reference in sorted(keys)
                ]
            )
            .on_conflict_do_nothing()
        )
    session.flush()


def web_link(settings: Settings, slug: str, path: str) -> str:
    base = (settings.costura_web_public_url or settings.costura_web_origin).rstrip("/")
    return f"{base}/o/{quote(slug)}?next={quote(path, safe='')}"


def signal_path(signal: Signal) -> str:
    if signal.kind == "anomaly":
        return f"/anomalies/{signal.reference}"
    if signal.kind == "budget":
        return "/budgets"
    if signal.kind == "sync_stale":
        return "/settings/connections"
    return f"/keys/{quote(signal.entity_id, safe='')}"


@dataclass(frozen=True)
class Views:
    signals: SignalView
    anomalies: AnomalyView


def views(session: Session, org_id: int) -> Views:
    return Views(
        signals=SignalView(session, org_id, ALL), anomalies=anomaly_view(session, org_id, ALL)
    )


def message(settings: Settings, slug: str, signal: Signal, seen: Views) -> str:
    """One Slack `text`: what happened (the anomaly sentence, or the label and the gap), the
    money at risk, the owner and a link."""
    if signal.anomaly is not None:
        what = explanation_of(seen.anomalies, signal.anomaly)
    else:
        what = f"{seen.signals.label(signal)}: {detail_of(signal)}."
    owner = seen.signals.owner(signal)
    money = f"{signal.dollars_at_risk.quantize(CENT):,.2f} USD"
    return (
        f"*{KIND_TITLES[signal.kind]}* ({signal.provider}) {what}"
        f" At risk: {money}. Owner: {owner.email if owner else 'nobody recorded'}."
        f" <{web_link(settings, slug, signal_path(signal))}|Open in Costura>"
    )


def signed_headers(signing_secret: str, body: bytes, delivery_id: str, now: int) -> dict[str, str]:
    digest = hmac.new(
        signing_secret.encode(), f"{now}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "User-Agent": "Costura-Webhook/1",
        "X-Costura-Delivery": delivery_id,
        "X-Costura-Timestamp": str(now),
        "X-Costura-Signature": f"{SIGNATURE_VERSION}={digest}",
    }


def http_post(url: str, body: bytes, headers: dict[str, str]) -> int:
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        return client.post(url, content=body, headers=headers).status_code


def send_text(
    settings: Settings, row: WebhookDestination, text: str, delivery_id: str, post: Post
) -> str | None:
    """Post one message; None on a 2xx, else the reason. The reason never holds the URL."""
    org_id = row.organization_id
    url = secrets.decrypt_bound(
        settings, secrets.webhook_context(org_id, "url"), row.url_ciphertext
    )
    signing_secret = secrets.decrypt_bound(
        settings, secrets.webhook_context(org_id, "secret"), row.secret_ciphertext
    )
    body = json.dumps({"text": text}).encode()
    try:
        status = post(
            url, body, signed_headers(signing_secret, body, delivery_id, int(time.time()))
        )
        error = None if 200 <= status < 300 else f"HTTP {status}"
    except httpx.HTTPError as exc:
        error = type(exc).__name__
    if error is None:
        row.last_success_at = datetime.now(UTC)
    else:
        row.last_failure_at = datetime.now(UTC)
        row.last_error = error
    return error


def deliver(
    session: Session,
    settings: Settings,
    org_id: int,
    *,
    post: Post | None = None,
    now: datetime | None = None,
) -> int:
    """Record the organization's new signals and post the due rows. Returns how many were
    sent. Hosts dropped from `COSTURA_WEBHOOK_HOSTS` after the save are not posted to."""
    row = destination(session, org_id)
    org = session.get(Organization, org_id)
    if row is None or org is None or row.url_host not in settings.webhook_hosts:
        return 0
    now = now or datetime.now(UTC)
    found = [s for s in current_signals(session, org_id) if s.kind not in NOT_POSTED]
    record_signals(session, org_id, found=found)
    by_key = {read_key(s): s for s in found}
    due = list(
        session.scalars(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.organization_id == org_id,
                WebhookDelivery.status == "pending",
                WebhookDelivery.next_attempt_at <= now,
            )
            .order_by(WebhookDelivery.created_at, WebhookDelivery.id)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    seen = views(session, org_id)
    sent = 0
    for delivery in due:
        signal = by_key.get((delivery.kind, delivery.provider, delivery.reference))
        if signal is None:
            delivery.status = "skipped"
            delivery.last_error = "closed before delivery"
            continue
        error = send_text(
            settings,
            row,
            message(settings, org.slug, signal, seen),
            str(delivery.id),
            post or http_post,
        )
        delivery.attempts += 1
        if error is None:
            delivery.status = "sent"
            delivery.sent_at = now
            delivery.last_error = None
            sent += 1
            if sent == 1:
                revive_failed(session, org_id, now)
            continue
        delivery.last_error = error
        if delivery.attempts >= MAX_ATTEMPTS:
            delivery.status = "failed"
        else:
            delivery.next_attempt_at = now + BACKOFF[min(delivery.attempts, len(BACKOFF)) - 1]
    session.flush()
    return sent


def send_test(
    session: Session, settings: Settings, org_id: int, *, post: Post | None = None
) -> str | None:
    """Post a test message to the saved destination; None when it answered 2xx."""
    row = destination(session, org_id)
    if row is None:
        raise InvalidInput("save a webhook URL first")
    if row.url_host not in settings.webhook_hosts:
        raise DeliveryOff()
    text = "Costura test message: new signals of this organization will arrive here."
    error = send_text(settings, row, text, "test", post or http_post)
    if error is None:
        revive_failed(session, org_id, datetime.now(UTC))
    session.flush()
    return error


def resend(
    session: Session, settings: Settings, org_id: int, delivery_id: int, *, post: Post | None = None
) -> str | None:
    """Post one recorded delivery again, rendered from the signal as it stands now (the
    payload is not stored); None when the destination answered 2xx. The same host and URL
    rules as the worker apply. 404 for a row of another organization, 422 once the signal
    closed, since there is nothing left to post."""
    row = destination(session, org_id)
    org = session.get(Organization, org_id)
    if row is None or org is None:
        raise InvalidInput("save a webhook URL first")
    if row.url_host not in settings.webhook_hosts:
        raise DeliveryOff()
    delivery = session.get(WebhookDelivery, delivery_id)
    if delivery is None or delivery.organization_id != org_id:
        raise NotFound(f"delivery {delivery_id} is not in this organization's history")
    by_key = {read_key(s): s for s in current_signals(session, org_id)}
    signal = by_key.get((delivery.kind, delivery.provider, delivery.reference))
    if signal is None:
        raise InvalidInput("the signal closed since it was recorded; there is nothing to resend")
    now = datetime.now(UTC)
    error = send_text(
        settings,
        row,
        message(settings, org.slug, signal, views(session, org_id)),
        str(delivery.id),
        post or http_post,
    )
    delivery.attempts += 1
    delivery.last_error = error
    if error is None:
        delivery.status = "sent"
        delivery.sent_at = now
        revive_failed(session, org_id, now)
    session.flush()
    return error


def revive_failed(session: Session, org_id: int, now: datetime) -> None:
    """The destination answers again: rows that gave up are tried once more on the next
    pass; a signal that closed meanwhile is skipped then."""
    session.execute(
        update(WebhookDelivery)
        .where(WebhookDelivery.organization_id == org_id, WebhookDelivery.status == "failed")
        .values(status="pending", attempts=0, next_attempt_at=now)
    )


def deliver_all(session_factory: Callable[[], Session], settings: Settings) -> int:
    """One pass over every organization with a destination, each in its own transaction so
    one failing organization does not hold back the others."""
    if not settings.webhook_hosts:
        return 0
    with session_factory() as session:
        org_ids = list(session.scalars(select(WebhookDestination.organization_id)))
    sent = 0
    for org_id in org_ids:
        with session_factory() as session:
            try:
                sent += deliver(session, settings, org_id)
                row = destination(session, org_id)
                if row is not None and row.url_host in settings.webhook_hosts:
                    from costura.digest import post_digest

                    post_digest(session, settings, row)
                session.commit()
            except Exception:
                session.rollback()
                log.exception("webhook delivery failed org_id=%s", org_id)
    return sent
