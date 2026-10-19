"""Google OIDC state, token verification, and verified-write boundary."""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session

from costura import auth, google_oidc
from costura.config import get_settings


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


class FakeGoogle:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.claims = {
            "iss": "https://accounts.google.com",
            "aud": "google-client",
            "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
            "nonce": "nonce-value",
            "email": "verified@example.com",
            "email_verified": True,
            "name": "Verified User",
        }
        self.signing_key = self.key
        self.requests: list[httpx.Request] = []

    def token(self) -> str:
        header = b64(json.dumps({"alg": "RS256", "kid": "key-1"}).encode())
        claims = b64(json.dumps(self.claims).encode())
        signed = f"{header}.{claims}".encode()
        signature = self.signing_key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
        return f"{header}.{claims}.{b64(signature)}"

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if str(request.url) == google_oidc.TOKEN_ENDPOINT:
            return httpx.Response(200, json={"id_token": self.token()})
        if str(request.url) == google_oidc.JWKS_ENDPOINT:
            public = self.key.public_key().public_numbers()
            return httpx.Response(
                200,
                json={
                    "keys": [
                        {
                            "kid": "key-1",
                            "kty": "RSA",
                            "alg": "RS256",
                            "use": "sig",
                            "n": b64(public.n.to_bytes((public.n.bit_length() + 7) // 8, "big")),
                            "e": b64(public.e.to_bytes((public.e.bit_length() + 7) // 8, "big")),
                        }
                    ]
                },
            )
        return httpx.Response(404)


@pytest.fixture
def google_settings(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "google-client")
    monkeypatch.setattr(settings, "google_client_secret", SecretStr("google-secret"))
    monkeypatch.setattr(settings, "costura_web_public_url", "https://costura.example.test")
    return settings


def test_state_nonce_and_pkce_are_one_use(db_session: Session, google_settings) -> None:
    started = google_oidc.begin(db_session, google_settings)
    query = httpx.QueryParams(httpx.URL(started.url).query)
    assert query["state"] == started.state
    assert query["nonce"] == started.nonce
    assert query["code_challenge_method"] == "S256"
    assert query["code_challenge"] == b64(hashlib.sha256(started.code_verifier.encode()).digest())

    google_oidc.consume(db_session, started.state, started.nonce, started.code_verifier)
    with pytest.raises(google_oidc.GoogleOidcError, match="already used"):
        google_oidc.consume(db_session, started.state, started.nonce, started.code_verifier)


@pytest.mark.parametrize("changed", ["state", "nonce", "code_verifier", "expired"])
def test_invalid_authorization_transaction_is_rejected(
    db_session: Session, google_settings, changed: str
) -> None:
    now = datetime.now(UTC)
    started = google_oidc.begin(db_session, google_settings, now=now)
    values = {
        "state": started.state,
        "nonce": started.nonce,
        "code_verifier": started.code_verifier,
    }
    if changed != "expired":
        values[changed] = f"wrong-{values[changed]}"
    checked_at = now + timedelta(minutes=11) if changed == "expired" else now
    with pytest.raises(google_oidc.GoogleOidcError, match="missing, expired, or already used"):
        google_oidc.consume(db_session, **values, now=checked_at)


@pytest.mark.parametrize(
    ("claim", "value", "message"),
    [
        ("iss", "https://issuer.invalid", "issuer"),
        ("aud", "another-client", "audience"),
        ("email_verified", False, "verify"),
        ("exp", 0, "expired"),
        ("nonce", "another-nonce", "nonce"),
    ],
)
def test_invalid_id_token_claims_are_rejected(
    google_settings, claim: str, value: object, message: str
) -> None:
    google = FakeGoogle()
    google.claims[claim] = value
    client = google_oidc.GoogleOidcClient(transport=httpx.MockTransport(google.handle))
    with pytest.raises(google_oidc.GoogleOidcError, match=message):
        client.complete(
            google_settings,
            code="code",
            nonce="nonce-value",
            code_verifier="verifier",
        )


def test_invalid_id_token_signature_is_rejected(google_settings) -> None:
    google = FakeGoogle()
    google.signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = google_oidc.GoogleOidcClient(transport=httpx.MockTransport(google.handle))
    with pytest.raises(google_oidc.GoogleOidcError, match="signature"):
        client.complete(
            google_settings,
            code="code",
            nonce="nonce-value",
            code_verifier="verifier",
        )


def test_google_must_return_an_id_token(google_settings) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == google_oidc.TOKEN_ENDPOINT
        return httpx.Response(200, json={"access_token": "not-an-id-token"})

    client = google_oidc.GoogleOidcClient(transport=httpx.MockTransport(handle))
    with pytest.raises(google_oidc.GoogleOidcError, match="did not return an ID token"):
        client.complete(
            google_settings,
            code="code",
            nonce="nonce-value",
            code_verifier="verifier",
        )


@pytest.mark.parametrize("token", ["one.two", "%%%..signature", "W10.W10.signature"])
def test_malformed_id_token_is_rejected(google_settings, token: str) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == google_oidc.TOKEN_ENDPOINT
        return httpx.Response(200, json={"id_token": token})

    client = google_oidc.GoogleOidcClient(transport=httpx.MockTransport(handle))
    with pytest.raises(google_oidc.GoogleOidcError, match=r"malformed|complete sign-in"):
        client.complete(
            google_settings,
            code="code",
            nonce="nonce-value",
            code_verifier="verifier",
        )


def test_unsupported_algorithm_and_unknown_key_are_rejected(google_settings) -> None:
    google = FakeGoogle()
    valid_token = google.token()
    _, claims, signature = valid_token.split(".")

    for header, message in (
        ({"alg": "HS256", "kid": "key-1"}, "unsupported signature"),
        ({"alg": "RS256", "kid": "unknown"}, "signing key is unknown"),
    ):
        token = f"{b64(json.dumps(header).encode())}.{claims}.{signature}"

        def handle(request: httpx.Request, current=token) -> httpx.Response:
            if str(request.url) == google_oidc.TOKEN_ENDPOINT:
                return httpx.Response(200, json={"id_token": current})
            return google.handle(request)

        client = google_oidc.GoogleOidcClient(transport=httpx.MockTransport(handle))
        with pytest.raises(google_oidc.GoogleOidcError, match=message):
            client.complete(
                google_settings,
                code="code",
                nonce="nonce-value",
                code_verifier="verifier",
            )


def test_multiple_audiences_require_authorized_party(google_settings) -> None:
    google = FakeGoogle()
    google.claims["aud"] = ["google-client", "other-client"]
    client = google_oidc.GoogleOidcClient(transport=httpx.MockTransport(google.handle))
    with pytest.raises(google_oidc.GoogleOidcError, match="authorized party"):
        client.complete(
            google_settings,
            code="code",
            nonce="nonce-value",
            code_verifier="verifier",
        )

    google.claims["azp"] = "google-client"
    identity = client.complete(
        google_settings,
        code="code",
        nonce="nonce-value",
        code_verifier="verifier",
    )
    assert identity.email == "verified@example.com"


def test_transport_and_json_failures_are_private(google_settings) -> None:
    responses = [
        httpx.Response(503, text="provider body"),
        httpx.Response(200, content=b"{not json"),
    ]
    for response in responses:
        client = google_oidc.GoogleOidcClient(
            transport=httpx.MockTransport(lambda _request, current=response: current)
        )
        with pytest.raises(google_oidc.GoogleOidcError, match="could not complete sign-in") as exc:
            client.complete(
                google_settings,
                code="code",
                nonce="nonce-value",
                code_verifier="verifier",
            )
        assert "provider body" not in str(exc.value)


def test_verified_identity_opens_google_session(google_settings, db_session: Session) -> None:
    google = FakeGoogle()
    identity = google_oidc.GoogleOidcClient(transport=httpx.MockTransport(google.handle)).complete(
        google_settings,
        code="code",
        nonce="nonce-value",
        code_verifier="verifier",
    )
    signed = auth.sign_in_google(db_session, identity.email, identity.name)
    assert auth.resolve_session_provider(db_session, signed.token) == "google"
    token_request = google.requests[0]
    form = dict(httpx.QueryParams(token_request.content.decode()))
    assert form["code_verifier"] == "verifier"
    assert form["client_secret"] == "google-secret"


def test_production_writes_require_google_session(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura.main import app

    monkeypatch.setattr(get_settings(), "costura_env", "production")
    monkeypatch.setattr(get_settings(), "costura_sign_up", "open")
    dev = auth.sign_in_dev(db_session, "dev@example.com")
    google = auth.sign_in_google(db_session, "google@example.com")
    db_session.commit()
    body = {"name": "Google", "slug": "google-org"}

    denied = TestClient(app, headers={"Authorization": f"Bearer {dev.token}"}).post(
        "/api/v1/orgs", json=body
    )
    assert denied.status_code == 403

    accepted = TestClient(app, headers={"Authorization": f"Bearer {google.token}"}).post(
        "/api/v1/orgs", json=body
    )
    assert accepted.status_code == 201
