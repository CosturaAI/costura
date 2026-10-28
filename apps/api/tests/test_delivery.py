"""Outbound delivery of signals to a Slack-compatible webhook: the host allowlist, the stored
URL, once-per-signal delivery with retries, the signature and the routes."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import delivery, secrets
from costura.config import Settings, get_settings
from costura.errors import InvalidInput
from costura.models import Organization, ProviderApiKey, WebhookDelivery, WebhookDestination
from tests.conftest import ORG_ID, account_of
from tests.seed import sync_run

URL = "https://hooks.slack.com/services/T000/B000/secretpath"
WEBHOOK = "/api/v1/orgs/default/webhook"


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    current = get_settings()
    monkeypatch.setattr(current, "costura_secret_key", SecretStr(secrets.generate_key()))
    monkeypatch.setattr(current, "costura_webhook_hosts", "hooks.slack.com, Example.org.")
    monkeypatch.setattr(current, "costura_web_public_url", "https://costura.example.com")
    return current


class Recorder:
    def __init__(self, *answers: int | BaseException) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> int:
        self.calls.append((url, body, headers))
        answer = self.answers.pop(0) if self.answers else 200
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _orphan_key(db_session: Session, external_id: str = "apikey_orphan") -> None:
    today = datetime.now(UTC).date()
    run = sync_run(db_session, ORG_ID, "anthropic", "api_keys", today, today)
    db_session.add(
        ProviderApiKey(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=account_of(db_session, ORG_ID, "anthropic"),
            sync_run_id=run.id,
            external_id=external_id,
            name="orphan",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            status="active",
        )
    )
    db_session.flush()


def _rows(db_session: Session) -> list[WebhookDelivery]:
    return list(db_session.scalars(select(WebhookDelivery).order_by(WebhookDelivery.id)))


def test_only_https_urls_on_an_allowed_host_pass(settings: Settings) -> None:
    assert delivery.check_url(settings, URL) == "hooks.slack.com"
    assert delivery.check_url(settings, "https://example.org/hook") == "example.org"
    for bad in (
        "http://hooks.slack.com/services/x",
        "https://someone@hooks.slack.com/x",
        "https://hooks.slack.com:8443/x",
        "https://evil.example.com/x",
        "https://" + "a" * 2050,
    ):
        with pytest.raises(InvalidInput) as refused:
            delivery.check_url(settings, bad)
        assert "secretpath" not in str(refused.value)

    off = settings.model_copy(update={"costura_webhook_hosts": ""})
    with pytest.raises(delivery.DeliveryOff):
        delivery.check_url(off, URL)


def test_the_url_is_stored_encrypted_and_open_signals_are_skipped(
    db_session: Session, settings: Settings
) -> None:
    _orphan_key(db_session)
    saved = delivery.save_destination(db_session, settings, ORG_ID, URL)

    row = db_session.get(WebhookDestination, ORG_ID)
    assert row is not None and URL.encode() not in row.url_ciphertext
    url_context = secrets.webhook_context(ORG_ID, "url")
    assert secrets.decrypt_bound(settings, url_context, row.url_ciphertext) == URL
    secret_context = secrets.webhook_context(ORG_ID, "secret")
    assert secrets.decrypt_bound(settings, secret_context, row.secret_ciphertext) == (
        saved.signing_secret
    )
    with pytest.raises(secrets.ContextMismatch):
        secrets.decrypt_bound(settings, secret_context, row.url_ciphertext)
    assert row.url_host == "hooks.slack.com"
    assert {r.status for r in _rows(db_session)} == {"skipped"}

    post = Recorder()
    assert delivery.deliver(db_session, settings, ORG_ID, post=post) == 0
    assert post.calls == []


def test_a_new_signal_is_posted_once_with_its_sentence_amount_link_and_signature(
    db_session: Session, settings: Settings
) -> None:
    saved = delivery.save_destination(db_session, settings, ORG_ID, URL)
    _orphan_key(db_session)

    post = Recorder()
    assert delivery.deliver(db_session, settings, ORG_ID, post=post) == 2
    assert delivery.deliver(db_session, settings, ORG_ID, post=post) == 0
    assert len(post.calls) == 2
    assert {r.kind: r.status for r in _rows(db_session)} == {
        "no_owner": "sent",
        "idle_active": "sent",
    }

    url, body, headers = post.calls[0]
    assert url == URL
    text = json.loads(body)["text"]
    assert "orphan" in text and "At risk: 0.00 USD." in text
    assert (
        "<https://costura.example.com/o/default?next=%2Fkeys%2Fapikey_orphan|Open in Costura>"
        in text
    )
    expected = hmac.new(
        saved.signing_secret.encode(),
        f"{headers['X-Costura-Timestamp']}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    assert headers["X-Costura-Signature"] == f"v1={expected}"
    assert headers["X-Costura-Delivery"].isdigit()


def test_failures_retry_with_backoff_then_fail_and_never_record_the_url(
    db_session: Session, settings: Settings
) -> None:
    delivery.save_destination(db_session, settings, ORG_ID, URL)
    _orphan_key(db_session)
    now = datetime.now(UTC) + timedelta(minutes=1)

    post = Recorder(500, httpx.ConnectError(f"cannot reach {URL}"))
    delivery.deliver(db_session, settings, ORG_ID, post=post, now=now)
    rows = _rows(db_session)
    assert [(r.status, r.attempts) for r in rows] == [("pending", 1), ("pending", 1)]
    assert sorted(r.last_error or "" for r in rows) == ["ConnectError", "HTTP 500"]
    assert all(r.next_attempt_at == now + timedelta(minutes=1) for r in rows)

    assert delivery.deliver(db_session, settings, ORG_ID, post=Recorder(), now=now) == 0
    failing = Recorder(*[503] * 10)
    later = now
    for _ in range(delivery.MAX_ATTEMPTS):
        later += timedelta(hours=3)
        delivery.deliver(db_session, settings, ORG_ID, post=failing, now=later)
    assert {(r.status, r.attempts) for r in _rows(db_session)} == {
        ("failed", delivery.MAX_ATTEMPTS)
    }


def test_a_signal_closed_before_its_turn_is_skipped(
    db_session: Session, settings: Settings
) -> None:
    delivery.save_destination(db_session, settings, ORG_ID, URL)
    _orphan_key(db_session)
    now = datetime.now(UTC) + timedelta(minutes=1)
    delivery.deliver(db_session, settings, ORG_ID, post=Recorder(500, 500), now=now)

    key = db_session.scalar(
        select(ProviderApiKey).where(ProviderApiKey.external_id == "apikey_orphan")
    )
    assert key is not None
    key.status = "archived"
    db_session.flush()
    post = Recorder()
    delivery.deliver(db_session, settings, ORG_ID, post=post, now=now + timedelta(hours=1))
    assert post.calls == []
    assert {(r.status, r.last_error) for r in _rows(db_session)} == {
        ("skipped", "closed before delivery")
    }


def test_a_host_dropped_from_the_allowlist_receives_nothing(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    delivery.save_destination(db_session, settings, ORG_ID, URL)
    _orphan_key(db_session)
    monkeypatch.setattr(settings, "costura_webhook_hosts", "example.org")
    post = Recorder()
    assert delivery.deliver(db_session, settings, ORG_ID, post=post) == 0
    assert post.calls == []


def test_routes_save_test_list_and_remove_the_webhook(
    client: TestClient, db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = client.get(WEBHOOK).json()
    assert before["egress_enabled"] is True and before["configured"] is False
    assert before["allowed_hosts"] == ["example.org", "hooks.slack.com"]

    assert client.put(WEBHOOK, json={"url": "https://evil.example.com/x"}).status_code == 422
    saved = client.put(WEBHOOK, json={"url": URL})
    assert saved.status_code == 200
    body = saved.json()
    assert body["configured"] is True and body["host"] == "hooks.slack.com"
    assert len(body["signing_secret"]) >= 32
    assert "secretpath" not in json.dumps(client.get(WEBHOOK).json())
    assert "signing_secret" not in client.get(WEBHOOK).json()

    post = Recorder(404)
    monkeypatch.setattr(delivery, "http_post", post)
    tested = client.post(f"{WEBHOOK}/test").json()
    assert tested == {"delivered": False, "error": "HTTP 404"}
    assert "test message" in json.loads(post.calls[0][1])["text"]

    removed = client.delete(WEBHOOK).json()
    assert removed["configured"] is False and removed["deliveries"] == []
    assert client.post(f"{WEBHOOK}/test").status_code == 422

    monkeypatch.setattr(settings, "costura_webhook_hosts", "")
    assert client.put(WEBHOOK, json={"url": URL}).status_code == 409


def test_a_pass_skips_everything_while_egress_is_off_and_posts_per_organization(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura.db import SessionLocal

    delivery.save_destination(db_session, settings, ORG_ID, URL)
    _orphan_key(db_session)
    db_session.commit()
    off = settings.model_copy(update={"costura_webhook_hosts": ""})
    assert delivery.deliver_all(SessionLocal, off) == 0

    post = Recorder()
    monkeypatch.setattr(delivery, "http_post", post)
    assert delivery.deliver_all(SessionLocal, settings) == 2
    assert len(post.calls) == 2


def test_a_failing_destination_is_a_signal_and_a_success_revives_failed_rows(
    db_session: Session, settings: Settings
) -> None:
    from costura.spend.signals import collect_signals

    delivery.save_destination(db_session, settings, ORG_ID, URL)
    _orphan_key(db_session)
    now = datetime.now(UTC) + timedelta(minutes=1)
    failing = Recorder(*[503] * 20)
    later = now
    for _ in range(delivery.MAX_ATTEMPTS):
        delivery.deliver(db_session, settings, ORG_ID, post=failing, now=later)
        later += timedelta(hours=3)
    assert {r.status for r in _rows(db_session)} == {"failed"}

    kinds = {s.kind for s in collect_signals(db_session, ORG_ID, "all")}
    assert "webhook_failing" in kinds
    assert "webhook_failing" not in {
        s.kind for s in collect_signals(db_session, ORG_ID, "anthropic")
    }
    assert delivery.deliver(db_session, settings, ORG_ID, post=Recorder(), now=later) == 0

    assert delivery.send_test(db_session, settings, ORG_ID, post=Recorder(200)) is None
    assert {r.status for r in _rows(db_session)} == {"pending"}
    assert "webhook_failing" not in {s.kind for s in collect_signals(db_session, ORG_ID, "all")}
    assert delivery.deliver(db_session, settings, ORG_ID, post=Recorder(), now=later) == 2
    assert all(r.kind != "webhook_failing" for r in _rows(db_session))


def test_the_digest_posts_once_on_its_day_with_the_month_and_open_signals(
    client: TestClient, db_session: Session, settings: Settings
) -> None:
    from datetime import date

    from costura.digest import due, post_digest

    delivery.save_destination(db_session, settings, ORG_ID, URL)
    _orphan_key(db_session)
    row = delivery.destination(db_session, ORG_ID)
    assert row is not None and row.digest == "off"
    monday = date(2026, 10, 19)
    assert not due(row, monday)

    assert client.put(f"{WEBHOOK}/digest", json={"digest": "weekly"}).json()["digest"] == "weekly"
    db_session.expire_all()
    row = delivery.destination(db_session, ORG_ID)
    assert row is not None
    assert due(row, monday) and not due(row, monday + timedelta(days=1))

    post = Recorder()
    assert post_digest(db_session, settings, row, today=monday, post=post) is None
    text = json.loads(post.calls[0][1])["text"]
    assert "Costura digest" in text and "Spend so far:" in text
    assert "Needs a person: 2 open" in text and "no owner: orphan" in text
    assert post_digest(db_session, settings, row, today=monday, post=post) is None
    assert len(post.calls) == 1
    assert client.put(f"{WEBHOOK}/digest", json={"digest": "daily"}).status_code == 422


def test_a_resend_posts_the_signal_again_and_revives_failed_rows(
    db_session: Session, settings: Settings
) -> None:
    saved = delivery.save_destination(db_session, settings, ORG_ID, URL)
    _orphan_key(db_session)
    now = datetime.now(UTC) + timedelta(minutes=1)
    failing = Recorder(*[503] * 20)
    later = now
    for _ in range(delivery.MAX_ATTEMPTS):
        delivery.deliver(db_session, settings, ORG_ID, post=failing, now=later)
        later += timedelta(hours=3)
    first, second = _rows(db_session)
    assert (first.status, second.status) == ("failed", "failed")

    post = Recorder(502)
    assert delivery.resend(db_session, settings, ORG_ID, first.id, post=post) == "HTTP 502"
    assert (first.status, first.attempts, first.last_error) == ("failed", 6, "HTTP 502")
    assert second.status == "failed"

    post = Recorder(200)
    assert delivery.resend(db_session, settings, ORG_ID, first.id, post=post) is None
    url, body, headers = post.calls[0]
    assert url == URL and "orphan" in json.loads(body)["text"]
    assert headers["X-Costura-Delivery"] == str(first.id)
    expected = hmac.new(
        saved.signing_secret.encode(),
        f"{headers['X-Costura-Timestamp']}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    assert headers["X-Costura-Signature"] == f"v1={expected}"
    assert (first.status, first.attempts, first.last_error) == ("sent", 7, None)
    assert first.sent_at is not None
    assert (second.status, second.attempts) == ("pending", 0)


def test_a_resend_refuses_a_closed_signal_a_foreign_row_and_a_blocked_host(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura.errors import NotFound

    with pytest.raises(InvalidInput, match="save a webhook URL first"):
        delivery.resend(db_session, settings, ORG_ID, 1, post=Recorder())
    delivery.save_destination(db_session, settings, ORG_ID, URL)
    _orphan_key(db_session)
    delivery.deliver(db_session, settings, ORG_ID, post=Recorder(500, 500))
    row = _rows(db_session)[0]

    with pytest.raises(NotFound):
        delivery.resend(db_session, settings, ORG_ID, row.id + 1000, post=Recorder())
    other = Organization(slug="other", name="Other")
    db_session.add(other)
    db_session.flush()
    delivery.save_destination(db_session, settings, other.id, URL)
    with pytest.raises(NotFound):
        delivery.resend(db_session, settings, other.id, row.id, post=Recorder())

    key = db_session.scalar(
        select(ProviderApiKey).where(ProviderApiKey.external_id == "apikey_orphan")
    )
    assert key is not None
    key.status = "archived"
    db_session.flush()
    post = Recorder()
    with pytest.raises(InvalidInput, match="closed"):
        delivery.resend(db_session, settings, ORG_ID, row.id, post=post)
    assert post.calls == [] and row.attempts == 1

    monkeypatch.setattr(settings, "costura_webhook_hosts", "example.org")
    with pytest.raises(delivery.DeliveryOff):
        delivery.resend(db_session, settings, ORG_ID, row.id, post=Recorder())


def test_the_resend_route_lists_ids_and_answers_the_outcome(
    client: TestClient, db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.put(WEBHOOK, json={"url": URL}).status_code == 200
    _orphan_key(db_session)
    delivery.deliver(db_session, settings, ORG_ID, post=Recorder(500, 500))
    db_session.commit()
    listed = client.get(WEBHOOK).json()["deliveries"]
    assert len(listed) == 2 and all(isinstance(d["id"], int) for d in listed)
    assert {d["status"] for d in listed} == {"pending"}

    post = Recorder(200)
    monkeypatch.setattr(delivery, "http_post", post)
    resent = client.post(f"{WEBHOOK}/deliveries/{listed[0]['id']}/resend")
    assert resent.status_code == 200 and resent.json() == {"delivered": True, "error": None}
    assert "secretpath" not in resent.text
    after = {d["id"]: d for d in client.get(WEBHOOK).json()["deliveries"]}
    assert after[listed[0]["id"]]["status"] == "sent"
    assert after[listed[0]["id"]]["attempts"] == 2

    missing = client.post(f"{WEBHOOK}/deliveries/{listed[0]['id'] + 1000}/resend")
    assert missing.status_code == 404
    monkeypatch.setattr(settings, "costura_webhook_hosts", "example.org")
    assert client.post(f"{WEBHOOK}/deliveries/{listed[0]['id']}/resend").status_code == 409


def test_a_gap_that_closes_and_comes_back_is_posted_again(
    db_session: Session, settings: Settings
) -> None:
    delivery.save_destination(db_session, settings, ORG_ID, URL)
    _orphan_key(db_session)
    post = Recorder()
    first = delivery.deliver(db_session, settings, ORG_ID, post=post)
    assert first > 0

    key = db_session.scalar(select(ProviderApiKey).where(ProviderApiKey.name == "orphan"))
    assert key is not None
    key.status = "archived"
    db_session.commit()
    assert delivery.deliver(db_session, settings, ORG_ID, post=post) == 0

    key.status = "active"
    db_session.commit()
    assert delivery.deliver(db_session, settings, ORG_ID, post=post) == first
    assert len(post.calls) == 2 * first
    closed = [r for r in _rows(db_session) if delivery.CLOSED_MARK in r.reference]
    assert len(closed) == first and {r.status for r in closed} == {"sent"}


def test_each_post_is_recorded_before_the_next_one_goes_out(
    db_session: Session, settings: Settings
) -> None:
    delivery.save_destination(db_session, settings, ORG_ID, URL)
    _orphan_key(db_session)
    _orphan_key(db_session, "apikey_second")

    class Stop(BaseException):
        pass

    post = Recorder(200, Stop())
    with pytest.raises(Stop):
        delivery.deliver(db_session, settings, ORG_ID, post=post)
    db_session.rollback()

    statuses = [r.status for r in _rows(db_session) if r.attempts > 0]
    assert statuses[0] == "sent"
    in_flight = [r for r in _rows(db_session) if r.attempts > 0 and r.status == "pending"]
    assert len(in_flight) == 1 and in_flight[0].next_attempt_at > datetime.now(UTC)


def test_a_failed_digest_waits_before_the_next_try_and_keeps_its_id(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura import digest

    monkeypatch.setattr(digest, "_last_failure", {})
    delivery.save_destination(db_session, settings, ORG_ID, URL)
    row = db_session.get(WebhookDestination, ORG_ID)
    assert row is not None
    row.digest = "weekly"
    monday = datetime.now(UTC).date() - timedelta(days=datetime.now(UTC).weekday())

    post = Recorder(500, 200)
    assert digest.post_digest(db_session, settings, row, today=monday, post=post) is not None
    assert digest.post_digest(db_session, settings, row, today=monday, post=post) is None
    assert len(post.calls) == 1
    assert post.calls[0][2]["X-Costura-Delivery"] == f"digest-{monday.isoformat()}"
