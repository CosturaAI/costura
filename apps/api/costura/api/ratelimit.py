"""Per-client request limits, kept in the process.

Four buckets, each a sliding one-minute window per client address: the sign-in and sign-out
routes (`auth`), every request other than GET, HEAD and OPTIONS (`write`), the reads of the
public sample organization (`demo`), the one path that answers without a session, and every
other read under `/api/v1` (`read`), counted per session token rather than per address so a
web server in front of many browsers does not share one limit. On top of `write`, storing a
provider key (connect, add an account, replace a key) is limited per organization
(`connect`), since each one calls the provider. A limit of 0 turns the bucket off; the
counters live in this process only, so a deployment with several API processes multiplies
them by the process count.

A limited response carries the IETF draft headers `RateLimit-Limit`, `RateLimit-Remaining`
and `RateLimit-Reset` (seconds until the oldest counted request leaves the window) for the
tightest bucket the request fell in; a 429 also carries `Retry-After` with the same seconds.

The client address is the TCP peer. When that peer is listed in `COSTURA_TRUSTED_PROXIES`
(an IP, a CIDR, or `*`), the address is the rightmost `X-Forwarded-For` hop that is not
itself a trusted proxy (`*` takes the rightmost hop). Otherwise the header is ignored.
Development-session writes use that same address: an untrusted forwarded header is still
refused, and a trusted proxy must present a loopback client (`guard.py`).
"""

import hashlib
import ipaddress
import math
import re
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from costura.api.deps import request_settings
from costura.config import Settings
from costura.identity_policy import normalize_email
from costura.models.organization import DEMO_ORG_SLUG

WINDOW_SECONDS = 60
MAX_KEYS = 10_000
TOO_MANY = "too many requests from this address; wait a minute and retry"
AUTH_PREFIX = "/api/v1/auth/"
DEMO_PREFIX = f"/api/v1/orgs/{DEMO_ORG_SLUG}"


API_PREFIX = "/api/v1/"
CONNECT_PATH = re.compile(
    r"^/api/v1/orgs/(?P<org>[^/]+)/providers/[^/]+/"
    r"(?:(?P<put>connection|accounts/[^/]+/key)|(?P<post>accounts))$"
)


def bucket_for(method: str, path: str) -> str | None:
    """`auth`, `write`, `demo`, `read`, or None outside `/api/v1` (health and metrics)."""
    if path.startswith(AUTH_PREFIX):
        return "auth"
    if method not in ("GET", "HEAD", "OPTIONS"):
        return "write"
    if path == DEMO_PREFIX or path.startswith(DEMO_PREFIX + "/"):
        return "demo"
    if path.startswith(API_PREFIX):
        return "read"
    return None


def connect_org(method: str, path: str) -> str | None:
    """The organization slug of a request that stores a provider key, else None."""
    found = CONNECT_PATH.match(path)
    if found is None:
        return None
    if (method == "PUT" and found["put"]) or (method == "POST" and found["post"]):
        return found["org"]
    return None


def _trusted_entries(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _peer_trusted(peer: str, entries: list[str]) -> bool:
    if "*" in entries:
        return True
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return peer in entries
    for entry in entries:
        if entry == peer:
            return True
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if address in network:
            return True
    return False


def client_address(request: Request) -> str:
    """Rate-limit address: the TCP peer, or the client appended by a trusted proxy."""
    peer = request.client.host if request.client else None
    if not peer:
        return "unknown"
    entries = _trusted_entries(request_settings(request).costura_trusted_proxies)
    if not entries or not _peer_trusted(peer, entries):
        return peer
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer
    hops = [part.strip() for part in forwarded.split(",") if part.strip()]
    if not hops:
        return peer
    for hop in reversed(hops):
        if not _peer_trusted(hop, entries):
            return hop
    return hops[-1]


def connecting_peer_is_trusted(request: Request) -> bool:
    """True when the TCP peer may supply `X-Forwarded-For`."""
    peer = request.client.host if request.client else None
    if not peer:
        return False
    entries = _trusted_entries(request_settings(request).costura_trusted_proxies)
    return bool(entries) and _peer_trusted(peer, entries)


def limit_for(bucket: str, settings: Settings) -> int:
    return {
        "auth": settings.costura_rate_limit_auth,
        "write": settings.costura_rate_limit_write,
        "demo": settings.costura_rate_limit_demo,
        "read": settings.costura_rate_limit_read,
        "connect": settings.costura_rate_limit_connect,
    }[bucket]


@dataclass(frozen=True)
class Verdict:
    """One bucket's answer: whether the hit fits, and the IETF draft rate-limit headers."""

    allowed: bool
    limit: int
    remaining: int
    reset: int

    def headers(self) -> dict[str, str]:
        return {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(self.remaining),
            "RateLimit-Reset": str(self.reset),
        }


@dataclass
class SlidingWindow:
    """Request timestamps per (bucket, client) over the last `WINDOW_SECONDS`, least recently
    seen first. At `MAX_KEYS` clients the idle ones go, then the least recently seen, down to
    half, so random keys (a new e-mail per sign-in) neither grow memory nor force a full scan
    on every request."""

    hits: OrderedDict[tuple[str, ...], deque[float]] = field(default_factory=OrderedDict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, key: tuple[str, ...], limit: int, now: float | None = None) -> bool:
        """Record one hit and say whether it stays within `limit` for the window."""
        return self.hit(key, limit, now).allowed

    def hit(self, key: tuple[str, ...], limit: int, now: float | None = None) -> Verdict:
        """Record one hit when it fits within `limit`; either way report what is left of the
        window and when its oldest counted hit expires."""
        now = time.monotonic() if now is None else now
        with self.lock:
            if key not in self.hits and len(self.hits) >= MAX_KEYS:
                self._shrink(now)
            window = self.hits.setdefault(key, deque())
            self.hits.move_to_end(key)
            while window and now - window[0] >= WINDOW_SECONDS:
                window.popleft()
            allowed = len(window) < limit
            if allowed:
                window.append(now)
            reset = math.ceil(WINDOW_SECONDS - (now - window[0])) if window else WINDOW_SECONDS
            return Verdict(allowed, limit, max(limit - len(window), 0), max(reset, 1))

    def _shrink(self, now: float) -> None:
        for key in [
            k for k, hits in self.hits.items() if not hits or now - hits[-1] >= WINDOW_SECONDS
        ]:
            del self.hits[key]
        while len(self.hits) > MAX_KEYS // 2:
            self.hits.popitem(last=False)

    def reset(self) -> None:
        with self.lock:
            self.hits.clear()


limiter = SlidingWindow()


def _session_subject(request: Request) -> str:
    """A digest of the bearer token, so reads are counted per session; empty without one."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return ""
    return hashlib.sha256(token.strip().encode()).hexdigest()[:32]


def _refused(verdict: Verdict) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": TOO_MANY},
        headers={"Retry-After": str(verdict.reset), **verdict.headers()},
    )


async def _auth_subject(request: Request, bucket: str) -> str:
    """The sign-in bucket is per address and e-mail, so two people behind one proxy do not
    share a limit. Other buckets ignore the body."""
    if bucket != "auth" or request.method != "POST":
        return ""
    try:
        payload = await request.json()
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    email = payload.get("email")
    if not isinstance(email, str) or "@" not in email:
        return ""
    return normalize_email(email)


async def rate_limit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    settings = request_settings(request)
    bucket = bucket_for(request.method, request.url.path)
    limit = limit_for(bucket, settings) if bucket is not None else 0
    verdicts: list[Verdict] = []
    if bucket is not None and limit > 0:
        subject = _session_subject(request) if bucket == "read" else ""
        client = "session" if subject else client_address(request)
        subject = subject or await _auth_subject(request, bucket)
        verdicts.append(limiter.hit((bucket, client, subject), limit))
        if not verdicts[-1].allowed:
            return _refused(verdicts[-1])
    org = connect_org(request.method, request.url.path)
    connect_limit = settings.costura_rate_limit_connect
    if org is not None and connect_limit > 0:
        verdicts.append(limiter.hit(("connect", "org", org), connect_limit))
        if not verdicts[-1].allowed:
            return _refused(verdicts[-1])
    response = await call_next(request)
    if verdicts:
        response.headers.update(min(verdicts, key=lambda v: v.remaining).headers())
    return response
