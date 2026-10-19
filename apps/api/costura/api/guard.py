"""Write-route identity guard.

Google-verified sessions may write in every environment. A development session for the
configured operator e-mail may write in every environment when the operator secret is set.
Any other development session may write only from loopback in explicit development or test
mode.
"""

import hashlib
import hmac
import ipaddress
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from costura import auth
from costura.api.deps import bearer_token, get_session, request_settings
from costura.api.ratelimit import client_address, connecting_peer_is_trusted
from costura.config import Settings
from costura.identity_policy import normalize_email

LOCAL_WRITE_ENVIRONMENTS = frozenset({"development", "test"})
WRITE_DISABLED = (
    "write routes require authentication with a Google-verified session, a configured "
    "operator session, or a development session on a development/test loopback stack"
)


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host == "testclient"
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or bool(mapped and mapped.is_loopback)


def _forwarded_only_from_loopback(request: Request) -> bool:
    peer = request.client.host if request.client else None
    hops = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",")]
    return is_loopback(peer) and all(is_loopback(hop) for hop in hops)


def require_local_write(request: Request) -> None:
    """Loopback only. A trusted proxy is judged by the resolved client; any other
    `X-Forwarded-For` is refused so a direct connection cannot spoof one. A loopback
    peer that forwards only loopback hops, as the local Next.js server does, is local."""
    if request_settings(request).costura_env not in LOCAL_WRITE_ENVIRONMENTS:
        raise HTTPException(status_code=403, detail=WRITE_DISABLED)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and not connecting_peer_is_trusted(request):
        if _forwarded_only_from_loopback(request):
            return
        raise HTTPException(status_code=403, detail=WRITE_DISABLED)
    if not is_loopback(client_address(request)):
        raise HTTPException(status_code=403, detail=WRITE_DISABLED)


def operator_sign_in_enabled(settings: Settings) -> bool:
    return settings.operator_available and settings.costura_env not in LOCAL_WRITE_ENVIRONMENTS


def operator_credentials_match(email: str, secret: str | None, settings: Settings) -> bool:
    expected_email = settings.normalized_operator_email
    expected_secret = settings.operator_secret_value()
    if expected_email is None or expected_secret is None:
        return False
    provided = secret or ""
    secret_ok = hmac.compare_digest(
        hashlib.sha256(provided.encode()).digest(),
        hashlib.sha256(expected_secret.encode()).digest(),
    )
    return secret_ok and normalize_email(email) == expected_email


def _operator_dev_session(session: Session, token: str, settings: Settings) -> bool:
    expected = settings.normalized_operator_email
    if not settings.operator_available or expected is None:
        return False
    if auth.resolve_session_provider(session, token) != "dev":
        return False
    user = auth.resolve_session(session, token)
    return user is not None and user.email == expected


def can_write(request: Request, session: Session) -> bool:
    token = bearer_token(request)
    if token is None:
        return False
    provider = auth.resolve_session_provider(session, token)
    if provider == "google":
        return True
    if provider == "dev" and _operator_dev_session(session, token, request_settings(request)):
        return True
    try:
        require_local_write(request)
    except HTTPException:
        return False
    return provider is not None


def require_verified_write(
    request: Request, session: Annotated[Session, Depends(get_session, scope="function")]
) -> None:
    if not can_write(request, session):
        raise HTTPException(status_code=403, detail=WRITE_DISABLED)


VerifiedWriteDep = Annotated[None, Depends(require_verified_write)]
