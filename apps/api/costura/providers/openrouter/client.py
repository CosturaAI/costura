"""Read-only client for the OpenRouter management API (bearer management key).

Policy enforced by `GuardedTransport`: GET anywhere under the base URL, plus POST to exactly
`/api/v1/analytics/query`, which is the analytics read endpoint and takes its query as a JSON
body by API design. Every other method or path raises `ReadOnlyViolation` before network I/O.
"""

import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Any

import httpx

from costura.providers.http import (
    ProviderApiError,
    ProviderAuthError,
    ProviderHttpClient,
    path_segment,
)
from costura.providers.normalization import rfc3339
from costura.providers.pages import FetchedPage as BasePage
from costura.providers.pagination import offset_pages

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
ANALYTICS_QUERY_PATH = "/analytics/query"
ANALYTICS_QUERY_FULL_PATH = "/api/v1/analytics/query"
KEY_PATH = "/key"
KEYS_PATH = "/keys"
WORKSPACES_PATH = "/workspaces"
ORGANIZATION_MEMBERS_PATH = "/organization/members"

# Analytics metrics the sync stores, in USD major units. `total_usage` includes the BYOK
# inference cost paid to the underlying provider; `credits_usage` is what OpenRouter bills to
# credits (including BYOK platform fees); `byok_usage` is the BYOK inference cost alone;
# `usage_web` the part billed for web search. Token metrics come back as strings.
ANALYTICS_METRICS = (
    "total_usage",
    "credits_usage",
    "byok_usage",
    "usage_web",
    "tokens_prompt",
    "tokens_completion",
    "cached_tokens",
    "reasoning_tokens",
    "request_count",
)
# The API resolves `api_key_id` to the key name in the response (see normalize.py).
COST_DIMENSIONS = ("api_key_id", "model")
ANALYTICS_ROW_LIMIT = 10_000
KEYS_PAGE_SIZE = 100


class OpenRouterApiError(ProviderApiError):
    pass


class OpenRouterAuthError(OpenRouterApiError, ProviderAuthError):
    """401 or 403: the key is not a management key, was revoked or lacks the permission."""


def allow_openrouter(request: httpx.Request) -> bool:
    if request.method == "GET":
        return True
    return request.method == "POST" and request.url.path == ANALYTICS_QUERY_FULL_PATH


class FetchedPage(BasePage):
    """One response plus the exact request (query params or JSON body) that produced it."""

    @property
    def results(self) -> list[dict[str, Any]]:
        """Analytics responses: `data.data` rows."""
        data = self.payload.get("data")
        if isinstance(data, dict):
            rows = data.get("data", [])
            return [row for row in rows if isinstance(row, dict)]
        return self.items

    @property
    def truncated(self) -> bool:
        data = self.payload.get("data")
        if isinstance(data, dict):
            return bool((data.get("metadata") or {}).get("truncated"))
        return False


class OpenRouterManagementClient:
    def __init__(
        self,
        *,
        management_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = ProviderHttpClient(
            base_url=base_url,
            headers={
                "authorization": f"Bearer {management_key}",
                "content-type": "application/json",
            },
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
            sleep=sleep,
            label="OpenRouter",
            api_error=OpenRouterApiError,
            auth_error=OpenRouterAuthError,
            allow=allow_openrouter,
        )
        self._client = self._http.client

    def __enter__(self) -> OpenRouterManagementClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def current_key(self) -> dict[str, Any]:
        """`GET /key`: the calling key's own record; `is_management_key` drives validation."""
        data = self._http.get(KEY_PATH, httpx.QueryParams()).get("data")
        if not isinstance(data, dict):
            raise OpenRouterApiError("GET /key returned no data object")
        return data

    def analytics_cost_pages(self, start: datetime, end: datetime) -> Iterator[FetchedPage]:
        """Daily spend and tokens per (key, model) over `[start, end)`."""
        return self._analytics_pages(start, end, COST_DIMENSIONS)

    def analytics_total_pages(self, start: datetime, end: datetime) -> Iterator[FetchedPage]:
        """Daily organization totals over `[start, end)`: the same query with no dimensions,
        one row per day. Used as the control total by `reconcile`."""
        return self._analytics_pages(start, end, ())

    def keys_pages(self) -> Iterator[FetchedPage]:
        """`GET /keys?include_disabled=true`, offset pagination of KEYS_PAGE_SIZE."""

        def fetch(offset: int) -> tuple[httpx.QueryParams, dict[str, Any]]:
            query = httpx.QueryParams({"include_disabled": "true", "offset": str(offset)})
            return query, self._http.get(KEYS_PATH, query)

        return (
            FetchedPage(**vars(page))
            for page in offset_pages(
                fetch, first_index=0, page_size=KEYS_PAGE_SIZE, items=_data_items
            )
        )

    def workspaces_pages(self) -> Iterator[FetchedPage]:
        yield self._single_page(WORKSPACES_PATH)

    def workspace_members_pages(self, workspace_id: str) -> Iterator[FetchedPage]:
        """Personal accounts answer 403 here; the caller skips (see inventory.py)."""
        yield self._single_page(f"{WORKSPACES_PATH}/{path_segment(workspace_id)}/members")

    def organization_members_pages(self) -> Iterator[FetchedPage]:
        """Personal accounts answer 404 here; the caller skips (see inventory.py)."""
        yield self._single_page(ORGANIZATION_MEMBERS_PATH)

    def _single_page(self, path: str) -> FetchedPage:
        query = httpx.QueryParams()
        return FetchedPage(page_index=0, request_params={}, payload=self._http.get(path, query))

    def _analytics_pages(
        self, start: datetime, end: datetime, dimensions: tuple[str, ...]
    ) -> Iterator[FetchedPage]:
        """One POST per window; a truncated response splits the window in halves (by day)
        until every piece fits in ANALYTICS_ROW_LIMIT rows."""
        if start >= end:
            raise ValueError("window start must be before window end")
        page_index = 0
        pending = [(start, end)]
        while pending:
            window_start, window_end = pending.pop(0)
            body = {
                "metrics": list(ANALYTICS_METRICS),
                "dimensions": list(dimensions),
                "granularity": "day",
                "time_range": {"start": rfc3339(window_start), "end": rfc3339(window_end)},
                "limit": ANALYTICS_ROW_LIMIT,
            }
            payload = self._http.send("POST", ANALYTICS_QUERY_PATH, json=body)
            page = FetchedPage(page_index=page_index, request_params=body, payload=payload)
            if page.truncated:
                days = (window_end - window_start).days
                if days < 2:
                    raise OpenRouterApiError(
                        f"analytics query for one day exceeds {ANALYTICS_ROW_LIMIT} rows: "
                        f"{rfc3339(window_start)}"
                    )
                middle = window_start + timedelta(days=days // 2)
                pending = [(window_start, middle), (middle, window_end), *pending]
                continue
            yield page
            page_index += 1


def _data_items(payload: dict[str, Any]) -> list[Any]:
    return FetchedPage(page_index=0, request_params={}, payload=payload).items


__all__ = [
    "ANALYTICS_METRICS",
    "COST_DIMENSIONS",
    "FetchedPage",
    "OpenRouterApiError",
    "OpenRouterAuthError",
    "OpenRouterManagementClient",
    "allow_openrouter",
]
