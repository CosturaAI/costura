import time
from collections.abc import Callable, Iterator
from datetime import datetime
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
from costura.providers.pagination import cursor_pages, split_window

ANTHROPIC_VERSION = "2023-06-01"
COST_REPORT_PATH = "/v1/organizations/cost_report"
USAGE_REPORT_PATH = "/v1/organizations/usage_report/messages"
WORKSPACES_PATH = "/v1/organizations/workspaces"
USERS_PATH = "/v1/organizations/users"
API_KEYS_PATH = "/v1/organizations/api_keys"
ORGANIZATION_PATH = "/v1/organizations/me"

# Listing endpoints (cursor pagination) accept up to 1000 items per page.
LIST_PAGE_SIZE = 1000

# Both report endpoints return at most 31 daily buckets per request.
MAX_DAILY_BUCKETS = 31

COST_GROUP_BY = ("workspace_id", "description")

# The usage report accepts at most 5 `group_by[]` dimensions ("Cannot specify more than 5
# `group_by[]` dimensions."). The cost grain needs seven, so the two enumerable ones are fixed
# per request through the `context_window[]` and `inference_geos[]` filters instead: one request
# per (context_window, inference_geo) slice, and the normalizer stamps the slice values onto the
# rows, which the API returns as null when the dimension is not grouped.
USAGE_GROUP_BY = ("api_key_id", "account_id", "workspace_id", "model", "service_tier")
CONTEXT_WINDOWS = ("0-200k", "200k-1M")
INFERENCE_GEOS = ("global", "not_available", "us")
USAGE_SLICES: tuple[tuple[str, str], ...] = tuple(
    (window, geo) for window in CONTEXT_WINDOWS for geo in INFERENCE_GEOS
)
CONTEXT_WINDOW_PARAM = "context_window[]"
INFERENCE_GEO_PARAM = "inference_geos[]"


class AnthropicApiError(ProviderApiError):
    pass


class AnthropicAuthError(AnthropicApiError, ProviderAuthError):
    """401 or 403: the Admin key is missing, revoked or lacks the permission."""


class FetchedPage(BasePage):
    """One response page plus the exact query that produced it."""

    @property
    def results(self) -> list[dict[str, Any]]:
        """Report endpoints: the results of every time bucket on the page."""
        results: list[dict[str, Any]] = []
        for bucket in self.payload.get("data", []):
            results.extend(bucket.get("results", []))
        return results


def day_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Split `[start, end)` into consecutive windows of at most MAX_DAILY_BUCKETS days."""
    return split_window(start, end, days=MAX_DAILY_BUCKETS)


class AnthropicAdminClient:
    """Synchronous, read-only client for the Anthropic Admin API report and listing endpoints.

    Every request goes through `GuardedTransport` with the GET-only policy."""

    def __init__(
        self,
        *,
        admin_key: str,
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = ProviderHttpClient(
            base_url=base_url,
            headers={
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
                "x-api-key": admin_key,
            },
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
            sleep=sleep,
            label="Anthropic",
            api_error=AnthropicApiError,
            auth_error=AnthropicAuthError,
        )
        self._client = self._http.client

    def __enter__(self) -> AnthropicAdminClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def cost_report_pages(self, start: datetime, end: datetime) -> Iterator[FetchedPage]:
        """Daily cost buckets grouped by workspace and description over `[start, end)`."""
        return self._report_pages(COST_REPORT_PATH, start, end, COST_GROUP_BY)

    def cost_total_pages(self, start: datetime, end: datetime) -> Iterator[FetchedPage]:
        """Daily organization totals over `[start, end)`: the cost report with no `group_by[]`,
        one result per day, the figure the Console Cost page sums. Used as a control total."""
        return self._report_pages(COST_REPORT_PATH, start, end, ())

    def usage_report_pages(self, start: datetime, end: datetime) -> Iterator[FetchedPage]:
        """Daily token buckets grouped by api key, account, workspace, model and tier over
        `[start, end)`, one pass per (context_window, inference_geo) slice; see USAGE_SLICES."""
        page_index = 0
        for window, geo in USAGE_SLICES:
            filters = [(CONTEXT_WINDOW_PARAM, window), (INFERENCE_GEO_PARAM, geo)]
            for page in self._report_pages(
                USAGE_REPORT_PATH, start, end, USAGE_GROUP_BY, filters, first_index=page_index
            ):
                yield page
                page_index = page.page_index + 1

    def workspaces_pages(self, *, include_archived: bool = True) -> Iterator[FetchedPage]:
        return self._cursor_pages(
            WORKSPACES_PATH, [("include_archived", str(include_archived).lower())]
        )

    def users_pages(self) -> Iterator[FetchedPage]:
        return self._cursor_pages(USERS_PATH, [])

    def api_keys_pages(self) -> Iterator[FetchedPage]:
        return self._cursor_pages(API_KEYS_PATH, [])

    def workspace_members_pages(self, workspace_id: str) -> Iterator[FetchedPage]:
        """Members of one workspace. Archived workspaces can answer 400/403/404; the caller
        decides whether to skip (see inventory.run_inventory_sync)."""
        return self._cursor_pages(f"{WORKSPACES_PATH}/{path_segment(workspace_id)}/members", [])

    def _cursor_pages(
        self, path: str, params: list[tuple[str, str]], *, first_index: int = 0
    ) -> Iterator[FetchedPage]:
        """Listing pagination: `has_more` plus `last_id`, next request `after_id=<last_id>`."""
        base = httpx.QueryParams(tuple(params)).set("limit", str(LIST_PAGE_SIZE))

        def fetch(cursor: str | None) -> tuple[httpx.QueryParams, dict[str, Any]]:
            query = base.set("after_id", cursor) if cursor is not None else base
            return query, self._http.get(path, query)

        return (
            FetchedPage(**vars(page))
            for page in cursor_pages(
                fetch,
                first_index=first_index,
                api_error=AnthropicApiError,
                cursor_field="last_id",
                missing_message="list page has has_more=true but no last_id",
            )
        )

    def _report_pages(
        self,
        path: str,
        start: datetime,
        end: datetime,
        group_by: tuple[str, ...],
        filters: list[tuple[str, str]] | None = None,
        *,
        first_index: int = 0,
    ) -> Iterator[FetchedPage]:
        page_index = first_index
        for window_start, window_end in day_windows(start, end):
            params: list[tuple[str, str]] = [
                ("starting_at", rfc3339(window_start)),
                ("ending_at", rfc3339(window_end)),
                ("bucket_width", "1d"),
                ("limit", str(MAX_DAILY_BUCKETS)),
            ]
            params.extend(("group_by[]", field) for field in group_by)
            params.extend(filters or [])
            for page in self._opaque_pages(path, params, first_index=page_index):
                yield page
                page_index = page.page_index + 1

    def _opaque_pages(
        self, path: str, params: list[tuple[str, str]], *, first_index: int
    ) -> Iterator[FetchedPage]:
        base = httpx.QueryParams(tuple(params))

        def fetch(cursor: str | None) -> tuple[httpx.QueryParams, dict[str, Any]]:
            query = base.set("page", cursor) if cursor is not None else base
            return query, self._http.get(path, query)

        return (
            FetchedPage(**vars(page))
            for page in cursor_pages(
                fetch,
                first_index=first_index,
                api_error=AnthropicApiError,
                missing_message="report page has has_more=true but no next_page",
            )
        )

    def organization(self) -> dict[str, Any]:
        """`GET /v1/organizations/me`: the organization the admin key belongs to (`id`,
        `name`), which labels the account it is connected as."""
        return self._http.get(ORGANIZATION_PATH, httpx.QueryParams())


__all__ = [
    "AnthropicAdminClient",
    "AnthropicApiError",
    "AnthropicAuthError",
    "FetchedPage",
    "day_windows",
]
