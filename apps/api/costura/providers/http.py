"""HTTP plumbing shared by provider clients: the sync guard and the retry loop.

Sync clients never create, edit or delete provider state. `GuardedTransport` makes that a
property of the client rather than a convention in calling code.
"""

import logging
import re
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any
from urllib.parse import quote

import httpx

MAX_RETRY_AFTER_SECONDS = 30.0
MAX_STORED_ERROR = 500
MAX_LOG_CHARS = 500
# Real credentials are long. Short prefixes in operator hints (`sk-ant-admin...`) stay.
_SECRET = re.compile(
    r"(?i)\b(?:bearer\s+[A-Za-z0-9._\-]{16,}|(?:sk|rk)-[A-Za-z0-9_\-]{16,}"
    r"|(?:key|crsr)_[A-Za-z0-9]{16,}|gAAAA[A-Za-z0-9_\-]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,})"
)
log = logging.getLogger("costura.providers")


def redact_secrets(text: str) -> str:
    """Replace obvious provider tokens, bearer values and Fernet blobs."""
    return _SECRET.sub("[redacted]", text)


def redact_and_cap(text: str, limit: int) -> str:
    """One line, secrets removed, cut at `limit` characters."""
    collapsed = " ".join(redact_secrets(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3] + "..."


def sanitize_stored_error(message: str | None) -> str | None:
    """Sentence safe to store or show: no provider body, no token, at most 500 characters."""
    if not message or not message.strip():
        return None
    text = message
    if " body=" in text:
        text = text.split(" body=", 1)[0].rstrip()
    cleaned = redact_and_cap(text, MAX_STORED_ERROR)
    return cleaned or None


Allow = Callable[[httpx.Request], bool]


class ProviderApiError(RuntimeError):
    """`str(exc)` carries everything the operator needs (status, request id, path, the body's
    first 300 characters) and goes to the server log; `public` is the sentence that may reach
    a browser or a stored `last_error`: provider, status and path, never the body."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        unavailable: bool = False,
        public: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.unavailable = unavailable
        self.public = public or message


def stored_exception_text(exc: BaseException) -> str:
    """What a sync run or credential may store. A provider error keeps its public sentence."""
    if isinstance(exc, ProviderApiError):
        return sanitize_stored_error(exc.public) or type(exc).__name__
    return sanitize_stored_error(f"{type(exc).__name__}: {exc}") or type(exc).__name__


def public_message(exc: BaseException) -> str:
    """The sentence that may be stored or shown for an exception out of a provider call: the
    `public` text of a `ProviderApiError`. The log line is capped and has tokens removed;
    the response body stays out of the returned sentence."""
    if isinstance(exc, ProviderApiError):
        log.warning("provider call failed: %s", type(exc).__name__)
        log.debug("provider response: %s", redact_and_cap(str(exc), MAX_LOG_CHARS))
        return sanitize_stored_error(exc.public) or type(exc).__name__
    return sanitize_stored_error(f"{type(exc).__name__}: {exc}") or type(exc).__name__


class ProviderAuthError(ProviderApiError):
    """401 or 403: the key is missing, revoked or lacks the permission."""


class ReadOnlyViolation(RuntimeError):
    """A request the provider policy forbids was about to leave the client; raised before any
    network I/O."""


def path_segment(value: str) -> str:
    """A provider id as one URL path segment: `/`, `?` and `#` are percent-encoded, and `.`
    or `..` (which a server would resolve against the path) are refused."""
    if value in {"", ".", ".."}:
        raise ValueError(f"not a usable path identifier: {value!r}")
    return quote(value, safe="")


def get_only(request: httpx.Request) -> bool:
    return request.method == "GET"


class GuardedTransport(httpx.BaseTransport):
    """Wraps the real transport so that only requests accepted by `allow` reach the network."""

    def __init__(self, inner: httpx.BaseTransport, *, allow: Allow = get_only, label: str) -> None:
        self._inner = inner
        self._allow = allow
        self._label = label

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if not self._allow(request):
            raise ReadOnlyViolation(
                f"refusing {request.method} {request.url.path}: the {self._label} client is "
                "read-only"
            )
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


def request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    params: httpx.QueryParams | None = None,
    json: Any | None = None,
    max_retries: int,
    sleep: Callable[[float], None] = time.sleep,
    label: str,
    api_error: type[ProviderApiError] = ProviderApiError,
    auth_error: type[ProviderAuthError] = ProviderAuthError,
) -> dict[str, Any]:
    """One logical request with exponential backoff on transport errors, 429 and 5xx.
    `retry-after` is honoured up to MAX_RETRY_AFTER_SECONDS. Other 4xx raise at once; 401 and
    403 raise `auth_error`."""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        delay = float(min(2**attempt, 8))
        try:
            response = client.request(method, path, params=params, json=json)
        except httpx.HTTPError as exc:
            last_error = exc
        else:
            retryable = response.status_code == 429 or response.status_code >= 500
            if response.is_success:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise api_error(
                        f"{label} response body is not valid JSON",
                        status_code=response.status_code,
                    ) from exc
                if not isinstance(payload, dict):
                    raise api_error(
                        f"{label} response body is not a JSON object",
                        status_code=response.status_code,
                    )
                return payload
            if not retryable:
                request_id = response.headers.get("request-id", "unknown")
                body = redact_secrets(response.text[:2000])[:300]
                message = (
                    f"{label} request failed: status={response.status_code} "
                    f"request_id={request_id} path={path} body={body!r}"
                )
                public = (
                    f"{label} answered HTTP {response.status_code} to {path} "
                    f"(request id {request_id})"
                )
                if response.status_code in (401, 403):
                    raise auth_error(message, status_code=response.status_code, public=public)
                raise api_error(message, status_code=response.status_code, public=public)
            last_error = api_error(
                f"{label} request failed: status={response.status_code} path={path}",
                status_code=response.status_code,
            )
            retry_after = response.headers.get("retry-after")
            if retry_after is not None:
                with suppress(ValueError):
                    delay = min(float(retry_after), MAX_RETRY_AFTER_SECONDS)
        if attempt == max_retries:
            break
        sleep(delay)
    last_status = getattr(last_error, "status_code", None)
    status_note = f" (last status {last_status})" if isinstance(last_status, int) else ""
    raise api_error(
        f"{label} request failed after {max_retries + 1} attempts: path={path} "
        f"last_error={last_error}",
        status_code=last_status if isinstance(last_status, int) else None,
        unavailable=True,
        public=(f"{label} did not answer {path} after {max_retries + 1} attempts{status_note}"),
    ) from last_error


class ProviderHttpClient:
    """The GET client every provider builds on: one guarded `httpx.Client`, the context
    manager, and `_get` with the provider's own error classes.

    Providers compose it rather than subclass it, so each client keeps its own method names
    and request shapes.
    """

    def __init__(
        self,
        *,
        base_url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        max_retries: int,
        transport: httpx.BaseTransport | None,
        sleep: Callable[[float], None],
        label: str,
        api_error: type[ProviderApiError],
        auth_error: type[ProviderAuthError],
        allow: Allow = get_only,
    ) -> None:
        self.max_retries = max_retries
        self.sleep = sleep
        self.label = label
        self.api_error = api_error
        self.auth_error = auth_error
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout_seconds,
            transport=GuardedTransport(
                transport or httpx.HTTPTransport(), allow=allow, label=label
            ),
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> ProviderHttpClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def get(self, path: str, params: httpx.QueryParams) -> dict[str, Any]:
        return request_json(
            self.client,
            "GET",
            path,
            params=params,
            max_retries=self.max_retries,
            sleep=self.sleep,
            label=self.label,
            api_error=self.api_error,
            auth_error=self.auth_error,
        )

    def send(
        self, method: str, path: str, *, params: httpx.QueryParams | None = None, json: Any = None
    ) -> dict[str, Any]:
        """A request the provider's transport policy allows. OpenRouter's analytics endpoint
        is POST and its client opts into that method."""
        return request_json(
            self.client,
            method,
            path,
            params=params,
            json=json,
            max_retries=self.max_retries,
            sleep=self.sleep,
            label=self.label,
            api_error=self.api_error,
            auth_error=self.auth_error,
        )


def params_as_dict(query: httpx.QueryParams) -> dict[str, Any]:
    """Multi-valued keys (`group_by[]`) become lists so the stored request is faithful."""
    result: dict[str, Any] = {}
    for key in query.keys():  # noqa: SIM118 - httpx.QueryParams.keys() lists every key, unlike Mapping.keys()
        values = query.get_list(key)
        result[key] = values if len(values) > 1 else values[0]
    return result
