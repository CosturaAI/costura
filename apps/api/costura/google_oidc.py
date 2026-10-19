"""Google OIDC authorization-code flow with one-use state, PKCE, and local JWT verification."""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from costura.config import Settings
from costura.models import OidcAuthorization

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
FLOW_TTL = timedelta(minutes=10)
HTTP_TIMEOUT = 10.0


class GoogleOidcError(ValueError):
    """A safe, public reason that the Google round trip was rejected."""


@dataclass(frozen=True)
class Authorization:
    url: str
    state: str
    nonce: str
    code_verifier: str
    expires_at: datetime


@dataclass(frozen=True)
class Identity:
    email: str
    name: str | None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _decode_b64url(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise GoogleOidcError("the ID token is malformed") from exc


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def begin(session: Session, settings: Settings, *, now: datetime | None = None) -> Authorization:
    if not settings.google_available:
        raise GoogleOidcError("Google sign-in is not configured")
    now = now or datetime.now(UTC)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    expires_at = now + FLOW_TTL
    session.execute(delete(OidcAuthorization).where(OidcAuthorization.expires_at <= now))
    session.add(
        OidcAuthorization(
            state_hash=_digest(state),
            nonce_hash=_digest(nonce),
            code_verifier_hash=_digest(code_verifier),
            expires_at=expires_at,
        )
    )
    session.flush()
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": _b64url(hashlib.sha256(code_verifier.encode()).digest()),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return Authorization(
        url=f"{AUTHORIZATION_ENDPOINT}?{query}",
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
        expires_at=expires_at,
    )


def consume(
    session: Session,
    state: str,
    nonce: str,
    code_verifier: str,
    *,
    now: datetime | None = None,
) -> None:
    """Consume before code exchange so a state cannot be replayed after any outcome."""
    now = now or datetime.now(UTC)
    row = session.scalar(
        select(OidcAuthorization)
        .where(OidcAuthorization.state_hash == _digest(state))
        .with_for_update()
    )
    valid = (
        row is not None
        and row.expires_at > now
        and hmac.compare_digest(row.nonce_hash, _digest(nonce))
        and hmac.compare_digest(row.code_verifier_hash, _digest(code_verifier))
    )
    if row is not None:
        session.delete(row)
        session.commit()
    if not valid:
        raise GoogleOidcError("the authorization request is missing, expired, or already used")


class GoogleOidcClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        now: datetime | None = None,
    ) -> None:
        self.transport = transport
        self.now = now

    def complete(
        self,
        settings: Settings,
        *,
        code: str,
        nonce: str,
        code_verifier: str,
    ) -> Identity:
        if not settings.google_available:
            raise GoogleOidcError("Google sign-in is not configured")
        secret = settings.google_client_secret
        assert secret is not None
        try:
            with httpx.Client(
                transport=self.transport, timeout=HTTP_TIMEOUT, follow_redirects=False
            ) as client:
                response = client.post(
                    TOKEN_ENDPOINT,
                    data={
                        "code": code,
                        "client_id": settings.google_client_id,
                        "client_secret": secret.get_secret_value(),
                        "redirect_uri": settings.google_redirect_uri,
                        "grant_type": "authorization_code",
                        "code_verifier": code_verifier,
                    },
                )
                response.raise_for_status()
                token_body = response.json()
                id_token = token_body.get("id_token") if isinstance(token_body, dict) else None
                if not isinstance(id_token, str):
                    raise GoogleOidcError("Google did not return an ID token")
                header, claims, signed, signature = _parse_token(id_token)
                keys_response = client.get(JWKS_ENDPOINT)
                keys_response.raise_for_status()
                jwks = keys_response.json()
        except GoogleOidcError:
            raise
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            raise GoogleOidcError("Google could not complete sign-in") from exc
        _verify_signature(header, signed, signature, jwks)
        return _verify_claims(
            claims,
            client_id=settings.google_client_id or "",
            nonce=nonce,
            now=self.now or datetime.now(UTC),
        )


def _parse_token(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    parts = token.split(".")
    if len(parts) != 3:
        raise GoogleOidcError("the ID token is malformed")
    try:
        header = json.loads(_decode_b64url(parts[0]))
        claims = json.loads(_decode_b64url(parts[1]))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GoogleOidcError("the ID token is malformed") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise GoogleOidcError("the ID token is malformed")
    return header, claims, f"{parts[0]}.{parts[1]}".encode(), _decode_b64url(parts[2])


def _verify_signature(header: dict[str, Any], signed: bytes, signature: bytes, jwks: Any) -> None:
    if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
        raise GoogleOidcError("the ID token uses an unsupported signature")
    keys = jwks.get("keys") if isinstance(jwks, dict) else None
    if not isinstance(keys, list):
        raise GoogleOidcError("Google returned an invalid signing-key set")
    key = next(
        (
            candidate
            for candidate in keys
            if isinstance(candidate, dict)
            and candidate.get("kid") == header["kid"]
            and candidate.get("kty") == "RSA"
            and candidate.get("use", "sig") == "sig"
            and candidate.get("alg", "RS256") == "RS256"
        ),
        None,
    )
    if key is None or not isinstance(key.get("n"), str) or not isinstance(key.get("e"), str):
        raise GoogleOidcError("the ID token signing key is unknown")
    try:
        numbers = rsa.RSAPublicNumbers(
            int.from_bytes(_decode_b64url(key["e"]), "big"),
            int.from_bytes(_decode_b64url(key["n"]), "big"),
        )
        numbers.public_key().verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    except (ValueError, InvalidSignature) as exc:
        raise GoogleOidcError("the ID token signature is invalid") from exc


def _verify_claims(
    claims: dict[str, Any], *, client_id: str, nonce: str, now: datetime
) -> Identity:
    if claims.get("iss") not in ISSUERS:
        raise GoogleOidcError("the ID token issuer is invalid")
    audience = claims.get("aud")
    audiences = [audience] if isinstance(audience, str) else audience
    if not isinstance(audiences, list) or client_id not in audiences:
        raise GoogleOidcError("the ID token audience is invalid")
    if len(audiences) > 1 and claims.get("azp") != client_id:
        raise GoogleOidcError("the ID token authorized party is invalid")
    expiry = claims.get("exp")
    if not isinstance(expiry, (int, float)) or expiry <= now.timestamp():
        raise GoogleOidcError("the ID token has expired")
    token_nonce = claims.get("nonce")
    if not isinstance(token_nonce, str) or not hmac.compare_digest(token_nonce, nonce):
        raise GoogleOidcError("the ID token nonce is invalid")
    email = claims.get("email")
    if claims.get("email_verified") is not True or not isinstance(email, str):
        raise GoogleOidcError("Google did not verify the e-mail address")
    name = claims.get("name")
    return Identity(email=email, name=name if isinstance(name, str) and name.strip() else None)
