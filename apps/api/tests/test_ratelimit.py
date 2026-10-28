"""Per-client request limits (`costura.api.ratelimit`)."""

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session
from starlette.requests import Request

from costura import secrets
from costura.api import ratelimit
from costura.api.ratelimit import (
    TOO_MANY,
    WINDOW_SECONDS,
    SlidingWindow,
    bucket_for,
    client_address,
    connect_org,
    limiter,
)
from costura.config import get_settings
from costura.models.organization import DEMO_ORG_SLUG
from costura.providers.anthropic.client import AnthropicAdminClient
from tests.conftest import request_session, seed_sample


def test_buckets_cover_sign_in_writes_and_the_public_sample_only() -> None:
    assert bucket_for("POST", "/api/v1/auth/dev-sign-in") == "auth"
    assert bucket_for("POST", "/api/v1/auth/sign-out") == "auth"
    assert bucket_for("PUT", "/api/v1/orgs/default/providers/anthropic/connection") == "write"
    assert bucket_for("PATCH", "/api/v1/orgs/default/providers/anthropic/anomalies/1") == "write"
    assert bucket_for("GET", f"/api/v1/orgs/{DEMO_ORG_SLUG}") == "demo"
    assert bucket_for("GET", f"/api/v1/orgs/{DEMO_ORG_SLUG}/setup") == "demo"
    # A member's read counts in `read`, as does a slug that merely starts with the sample's.
    assert bucket_for("GET", "/api/v1/orgs/default/setup") == "read"
    assert bucket_for("GET", f"/api/v1/orgs/{DEMO_ORG_SLUG}2/setup") == "read"
    assert bucket_for("GET", "/health") is None
    assert bucket_for("GET", "/live") is None
    assert bucket_for("GET", "/ready") is None


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/live",
            "raw_path": b"/live",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 12345),
            "server": ("test", 80),
        }
    )


def test_trusted_proxy_uses_the_appended_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "costura_trusted_proxies", "")
    forged = _request("10.0.0.8", "203.0.113.5")
    assert client_address(forged) == "10.0.0.8"

    monkeypatch.setattr(get_settings(), "costura_trusted_proxies", "*")
    assert client_address(_request("10.0.0.8", "1.1.1.1, 203.0.113.5")) == "203.0.113.5"

    monkeypatch.setattr(get_settings(), "costura_trusted_proxies", "172.28.100.0/24")
    proxied = _request("172.28.100.2", "1.1.1.1, 203.0.113.5, 172.28.100.2")
    assert client_address(proxied) == "203.0.113.5"
    assert client_address(_request("203.0.113.9", "1.1.1.1")) == "203.0.113.9"


def test_a_trusted_proxy_may_present_a_loopback_client(
    db_session: Session, owner_auth: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura.api.deps import get_session
    from costura.main import app

    monkeypatch.setattr(get_settings(), "costura_trusted_proxies", "10.0.0.1")
    app.dependency_overrides[get_session] = request_session(db_session)
    headers = {"Authorization": owner_auth}
    path = "/api/v1/orgs/default/providers/anthropic/connection"
    try:
        with TestClient(app, client=("10.0.0.1", 50000), headers=headers) as proxy:
            allowed = proxy.get(path, headers={**headers, "X-Forwarded-For": "127.0.0.1"})
            refused = proxy.get(path, headers={**headers, "X-Forwarded-For": "203.0.113.4"})
        assert allowed.json()["writes_enabled"] is True
        assert refused.json()["writes_enabled"] is False
        with TestClient(app, client=("127.0.0.1", 50000), headers=headers) as direct:
            local = direct.get(path, headers={**headers, "X-Forwarded-For": "127.0.0.1"})
            forged = direct.get(path, headers={**headers, "X-Forwarded-For": "203.0.113.4"})
        assert local.json()["writes_enabled"] is True
        assert forged.json()["writes_enabled"] is False
    finally:
        app.dependency_overrides.clear()


def test_window_slides_per_key() -> None:
    window = SlidingWindow()
    assert [window.allow(("auth", "a"), 2, now=t) for t in (0.0, 1.0, 2.0)] == [True, True, False]
    # Another client has its own count; the first client's hits expire after the window.
    assert window.allow(("auth", "b"), 2, now=2.0)
    assert window.allow(("auth", "a"), 2, now=WINDOW_SECONDS + 0.5)
    assert window.allow(("auth", "a"), 2, now=WINDOW_SECONDS + 1.5)
    assert not window.allow(("auth", "a"), 2, now=WINDOW_SECONDS + 1.9)


def test_a_hit_reports_the_limit_what_is_left_and_when_the_window_resets() -> None:
    window = SlidingWindow()
    first = window.hit(("read", "session", "s1"), 3, now=10.0)
    assert (first.allowed, first.limit, first.remaining, first.reset) == (True, 3, 2, 60)
    assert window.hit(("read", "session", "s1"), 3, now=30.5).remaining == 1
    third = window.hit(("read", "session", "s1"), 3, now=40.0)
    assert (third.allowed, third.remaining, third.reset) == (True, 0, 30)
    refused = window.hit(("read", "session", "s1"), 3, now=50.0)
    assert (refused.allowed, refused.remaining, refused.reset) == (False, 0, 20)
    assert refused.headers() == {
        "RateLimit-Limit": "3",
        "RateLimit-Remaining": "0",
        "RateLimit-Reset": "20",
    }
    # The oldest hit expires at 70.0: a hit then is counted and the reset is at least 1.
    after = window.hit(("read", "session", "s1"), 3, now=70.0)
    assert (after.allowed, after.remaining, after.reset) == (True, 0, 21)
    assert window.hit(("read", "session", "s2"), 3, now=99.9999).reset == 60


def test_window_keeps_at_most_max_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 4)
    window = SlidingWindow()
    for i in range(4):
        window.allow(("auth", "ip", f"old{i}"), 5, now=0.0)
    window.allow(("auth", "ip", "fresh"), 5, now=WINDOW_SECONDS + 1)
    assert list(window.hits) == [("auth", "ip", "fresh")]
    for i in range(10):
        window.allow(("auth", "ip", f"live{i}"), 5, now=WINDOW_SECONDS + 2)
    assert len(window.hits) <= 4


def test_window_evicts_the_least_recently_seen_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 4)
    window = SlidingWindow()
    for name in ("a", "b", "c", "d"):
        window.allow(("auth", "ip", name), 5, now=1.0)
    window.allow(("auth", "ip", "a"), 5, now=2.0)
    window.allow(("auth", "ip", "e"), 5, now=3.0)
    assert ("auth", "ip", "a") in window.hits
    assert ("auth", "ip", "b") not in window.hits


def test_sign_in_answers_429_past_the_limit(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura.main import app

    monkeypatch.setattr(get_settings(), "costura_rate_limit_auth", 3)
    anonymous = TestClient(app)
    body = {"email": "burst@example.com"}
    answers = [anonymous.post("/api/v1/auth/dev-sign-in", json=body) for _ in range(4)]
    assert [r.status_code for r in answers] == [201, 201, 201, 429]
    assert [r.headers["ratelimit-limit"] for r in answers] == ["3"] * 4
    assert [r.headers["ratelimit-remaining"] for r in answers] == ["2", "1", "0", "0"]
    refused = anonymous.post("/api/v1/auth/dev-sign-in", json=body)
    assert refused.json() == {"detail": TOO_MANY, "code": "rate_limited"}
    assert refused.headers["retry-after"] == refused.headers["ratelimit-reset"]
    assert 1 <= int(refused.headers["retry-after"]) <= WINDOW_SECONDS
    # The sign-in bucket does not touch the sample organization's reads.
    seed_sample(db_session)
    assert anonymous.get(f"/api/v1/orgs/{DEMO_ORG_SLUG}").status_code == 200


def test_a_limit_of_zero_turns_the_bucket_off(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura.main import app

    monkeypatch.setattr(get_settings(), "costura_rate_limit_auth", 0)
    anonymous = TestClient(app)
    body = {"email": "burst@example.com"}
    assert all(
        anonymous.post("/api/v1/auth/dev-sign-in", json=body).status_code == 201 for _ in range(5)
    )


def test_key_stores_are_the_connect_writes() -> None:
    base = "/api/v1/orgs/acme/providers/anthropic"
    assert connect_org("PUT", f"{base}/connection") == "acme"
    assert connect_org("POST", f"{base}/accounts") == "acme"
    assert connect_org("PUT", f"{base}/accounts/3/key") == "acme"
    assert connect_org("DELETE", f"{base}/connection") is None
    assert connect_org("PATCH", f"{base}/accounts/3") is None
    assert connect_org("PUT", f"{base}/budgets/org/__org__") is None


def test_reads_are_limited_per_session(
    client: TestClient, member_auth: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura.main import app

    monkeypatch.setattr(get_settings(), "costura_rate_limit_read", 3)
    answers = [client.get("/api/v1/orgs/default/setup") for _ in range(4)]
    assert [r.status_code for r in answers] == [200, 200, 200, 429]
    assert [r.headers["ratelimit-remaining"] for r in answers] == ["2", "1", "0", "0"]
    # Another session behind the same address keeps its own window.
    member = TestClient(app, headers={"Authorization": member_auth})
    fresh = member.get("/api/v1/orgs/default/setup")
    assert fresh.status_code == 200 and fresh.headers["ratelimit-remaining"] == "2"
    # Probes are not limited and carry no rate-limit headers.
    live = client.get("/live")
    assert live.status_code == 200 and "ratelimit-limit" not in live.headers


def test_unknown_tokens_share_the_sender_address_window(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura.main import app

    monkeypatch.setattr(get_settings(), "costura_rate_limit_read", 3)
    statuses = [
        TestClient(app, headers={"Authorization": f"Bearer random-{n}"})
        .get("/api/v1/orgs/default/setup")
        .status_code
        for n in range(5)
    ]
    assert statuses == [401, 401, 401, 429, 429]
    assert not any(key[1] == "session" for key in limiter.hits)


def test_key_stores_are_limited_per_organization(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "costura_rate_limit_connect", 2)
    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(secrets.generate_key()))
    original_init = AnthropicAdminClient.__init__

    def rejecting_init(self, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})
        )
        original_init(self, **kwargs)

    monkeypatch.setattr(AnthropicAdminClient, "__init__", rejecting_init)
    url = "/api/v1/orgs/default/providers/anthropic/connection"
    answers = [client.put(url, json={"admin_key": "x"}) for _ in range(3)]
    assert [r.status_code for r in answers] == [422, 422, 429]
    # The headers describe the tightest bucket: the per-organization key store, not `write`.
    assert [r.headers["ratelimit-limit"] for r in answers] == ["2"] * 3
    assert [r.headers["ratelimit-remaining"] for r in answers] == ["1", "0", "0"]
    assert answers[2].headers["retry-after"] == answers[2].headers["ratelimit-reset"]
