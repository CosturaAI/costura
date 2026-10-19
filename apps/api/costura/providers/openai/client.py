"""Read-only client for the OpenAI Admin API (bearer admin key, `sk-admin-...`).

Policy enforced by `GuardedTransport`: GET only, anywhere under the base URL. Every
organization read Costura needs (costs, usage, projects, users, project keys and members) is a
GET, so no write verb is ever allowed.

Window arguments are timezone-aware datetimes; the API takes Unix seconds with `start_time`
inclusive and `end_time` exclusive, and buckets days in UTC.
"""

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

from costura.providers.http import (
    ProviderApiError,
    ProviderAuthError,
    ProviderHttpClient,
    path_segment,
)
from costura.providers.pages import FetchedPage as BasePage
from costura.providers.pagination import cursor_pages

DEFAULT_BASE_URL = "https://api.openai.com/v1"
COSTS_PATH = "/organization/costs"
USAGE_COMPLETIONS_PATH = "/organization/usage/completions"
PROJECTS_PATH = "/organization/projects"
USERS_PATH = "/organization/users"

# `line_item` names the model and the token kind ("gpt-4o-mini, input"), so grouping by it
# gives the (model, token type) buckets the token-share allocation prices.
COST_GROUP_BY = ("project_id", "api_key_id", "line_item")
COST_BY_KEY_GROUP_BY = ("project_id", "api_key_id")
USAGE_GROUP_BY = ("project_id", "api_key_id", "user_id", "model")
USAGE_FAMILY_GROUP_BY: dict[str, tuple[str, ...]] = {
    "images": ("project_id", "api_key_id", "user_id", "model", "size", "source"),
    "embeddings": USAGE_GROUP_BY,
    "moderations": USAGE_GROUP_BY,
    "audio_speeches": USAGE_GROUP_BY,
    "audio_transcriptions": USAGE_GROUP_BY,
    "vector_stores": ("project_id",),
    "code_interpreter_sessions": ("project_id",),
}
BUCKET_WIDTH = "1d"
# Buckets per page: the costs endpoint accepts up to 180 days, the usage endpoint 31 at `1d`.
COSTS_PAGE_LIMIT = 180
USAGE_PAGE_LIMIT = 31
LISTING_PAGE_LIMIT = 100


class OpenAIApiError(ProviderApiError):
    pass


class OpenAIAuthError(OpenAIApiError, ProviderAuthError):
    """401 or 403: the key is not an admin key, was revoked or lacks the read permission."""


class FetchedPage(BasePage):
    """One response plus the exact query that produced it."""

    @property
    def buckets(self) -> list[dict[str, Any]]:
        """Report responses: the day buckets in `data`, each with its `results`."""
        data = self.payload.get("data", [])
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict) and item.get("object") == "bucket"]

    @property
    def results(self) -> list[dict[str, Any]]:
        """Report responses: every result row of every bucket on the page."""
        rows: list[dict[str, Any]] = []
        for bucket in self.buckets:
            rows.extend(row for row in bucket.get("results", []) if isinstance(row, dict))
        return rows

    @property
    def next_page(self) -> str | None:
        cursor = self.payload.get("next_page")
        return cursor if isinstance(cursor, str) and cursor else None

    @property
    def has_more(self) -> bool:
        return self.payload.get("has_more") is True

    @property
    def last_id(self) -> str | None:
        value = self.payload.get("last_id")
        if isinstance(value, str) and value:
            return value
        items = self.items
        last = items[-1].get("id") if items else None
        return last if isinstance(last, str) and last else None


def unix_seconds(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return int(value.astimezone(UTC).timestamp())


class OpenAIAdminClient:
    def __init__(
        self,
        *,
        admin_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = ProviderHttpClient(
            base_url=base_url,
            headers={
                "authorization": f"Bearer {admin_key}",
                "content-type": "application/json",
            },
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
            sleep=sleep,
            label="OpenAI",
            api_error=OpenAIApiError,
            auth_error=OpenAIAuthError,
        )
        self._client = self._http.client

    def __enter__(self) -> OpenAIAdminClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def costs_pages(self, start: datetime, end: datetime) -> Iterator[FetchedPage]:
        """Daily billed money per (project, line item) over `[start, end)`."""
        return self._report_pages(COSTS_PATH, start, end, COST_GROUP_BY, COSTS_PAGE_LIMIT)

    def costs_total_pages(self, start: datetime, end: datetime) -> Iterator[FetchedPage]:
        """Daily organization totals over `[start, end)`: the same query without `group_by`,
        one result per day. Used as the control total by `reconcile`."""
        return self._report_pages(COSTS_PATH, start, end, (), COSTS_PAGE_LIMIT)

    def costs_by_key_pages(self, start: datetime, end: datetime) -> Iterator[FetchedPage]:
        """Daily billed money per (project, API key): the provider's own per-key figure that
        `reconcile` sets beside the token-share allocation."""
        return self._report_pages(COSTS_PATH, start, end, COST_BY_KEY_GROUP_BY, COSTS_PAGE_LIMIT)

    def usage_completions_pages(self, start: datetime, end: datetime) -> Iterator[FetchedPage]:
        """Daily tokens and requests per (project, key, user, model) over `[start, end)`."""
        return self._report_pages(
            USAGE_COMPLETIONS_PATH, start, end, USAGE_GROUP_BY, USAGE_PAGE_LIMIT
        )

    def usage_family_pages(
        self, family: str, start: datetime, end: datetime
    ) -> Iterator[FetchedPage]:
        """Daily non-completions usage at the finest grouping that family supports."""
        try:
            group_by = USAGE_FAMILY_GROUP_BY[family]
        except KeyError as exc:
            raise ValueError(f"unknown OpenAI usage family: {family!r}") from exc
        return self._report_pages(
            f"/organization/usage/{family}",
            start,
            end,
            group_by,
            USAGE_PAGE_LIMIT,
        )

    def projects_pages(self) -> Iterator[FetchedPage]:
        return self._listing_pages(PROJECTS_PATH, {"include_archived": "true"})

    def users_pages(self) -> Iterator[FetchedPage]:
        return self._listing_pages(USERS_PATH, {})

    def project_api_keys_pages(self, project_id: str) -> Iterator[FetchedPage]:
        """Keys of one project, including those whose owner lost access to it: a key that
        spent money this month is a key to name, whoever holds it now."""
        return self._listing_pages(
            f"{PROJECTS_PATH}/{path_segment(project_id)}/api_keys", {"owner_project_access": "any"}
        )

    def project_users_pages(self, project_id: str) -> Iterator[FetchedPage]:
        return self._listing_pages(f"{PROJECTS_PATH}/{path_segment(project_id)}/users", {})

    def _report_pages(
        self,
        path: str,
        start: datetime,
        end: datetime,
        group_by: tuple[str, ...],
        limit: int,
    ) -> Iterator[FetchedPage]:
        """Cursor pagination over day buckets: `next_page` until `has_more` is false."""
        if start >= end:
            raise ValueError("window start must be before window end")
        base: list[tuple[str, str | int | float | None]] = [
            ("start_time", str(unix_seconds(start))),
            ("end_time", str(unix_seconds(end))),
            ("bucket_width", BUCKET_WIDTH),
            ("limit", str(limit)),
        ]
        base.extend(("group_by", field) for field in group_by)

        def fetch(cursor: str | None) -> tuple[httpx.QueryParams, dict[str, Any]]:
            params = [*base, ("page", cursor)] if cursor is not None else base
            query = httpx.QueryParams(params)
            return query, self._http.get(path, query)

        return (
            FetchedPage(**vars(page))
            for page in cursor_pages(fetch, first_index=0, api_error=OpenAIApiError)
        )

    def _listing_pages(self, path: str, extra: dict[str, str]) -> Iterator[FetchedPage]:
        """Object-id pagination: `after` the last id of the previous page until `has_more`."""
        base = httpx.QueryParams({**extra, "limit": str(LISTING_PAGE_LIMIT)})

        def fetch(cursor: str | None) -> tuple[httpx.QueryParams, dict[str, Any]]:
            query = base.set("after", cursor) if cursor is not None else base
            payload = self._http.get(path, query)
            page = FetchedPage(page_index=0, request_params={}, payload=payload)
            return query, {**payload, "next_page": page.last_id}

        return (
            FetchedPage(**vars(page))
            for page in cursor_pages(fetch, first_index=0, api_error=OpenAIApiError)
        )


__all__ = [
    "COST_BY_KEY_GROUP_BY",
    "COST_GROUP_BY",
    "USAGE_FAMILY_GROUP_BY",
    "USAGE_GROUP_BY",
    "FetchedPage",
    "OpenAIAdminClient",
    "OpenAIApiError",
    "OpenAIAuthError",
    "unix_seconds",
]
