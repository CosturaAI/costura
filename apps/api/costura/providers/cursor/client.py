"""Read-only client for Cursor's team Admin API.

Cursor uses Basic authentication with the API key as the username. Usage timestamps and both
request bounds are epoch milliseconds; Costura's half-open windows become an inclusive end by
subtracting one millisecond.
"""

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from costura.providers.http import (
    ProviderApiError,
    ProviderAuthError,
    ProviderHttpClient,
)
from costura.providers.pages import FetchedPage as BasePage
from costura.providers.pagination import MAX_PAGES

DEFAULT_BASE_URL = "https://api.cursor.com"
MEMBERS_PATH = "/teams/members"
FILTERED_USAGE_EVENTS_PATH = "/teams/filtered-usage-events"
DAILY_USAGE_PATH = "/teams/daily-usage-data"
SPEND_PATH = "/teams/spend"
MAX_PAGE_SIZE = 1000
MAX_WINDOW_DAYS = 30


class CursorApiError(ProviderApiError):
    pass


class CursorAuthError(CursorApiError, ProviderAuthError):
    """401 or 403: the team API key is invalid, revoked, or lacks team access."""


def allow_cursor(request: httpx.Request) -> bool:
    return (request.method == "GET" and request.url.path == MEMBERS_PATH) or (
        request.method == "POST"
        and request.url.path in (FILTERED_USAGE_EVENTS_PATH, DAILY_USAGE_PATH, SPEND_PATH)
    )


class FetchedPage(BasePage):
    @property
    def results(self) -> list[dict[str, Any]]:
        rows = next(
            (
                self.payload[key]
                for key in ("usageEvents", "data", "teamMemberSpend")
                if isinstance(self.payload.get(key), list)
            ),
            [],
        )
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    @property
    def items(self) -> list[dict[str, Any]]:
        rows = self.payload.get("teamMembers", [])
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def epoch_milliseconds(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return int(value.astimezone(UTC).timestamp() * 1000)


class CursorAdminClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = ProviderHttpClient(
            base_url=base_url,
            headers={"content-type": "application/json"},
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
            sleep=sleep,
            label="Cursor",
            api_error=CursorApiError,
            auth_error=CursorAuthError,
            allow=allow_cursor,
        )
        self._client = self._http.client
        self._client.auth = httpx.BasicAuth(api_key, "")

    def __enter__(self) -> CursorAdminClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def members_pages(self) -> Iterator[FetchedPage]:
        payload = self._request("GET", MEMBERS_PATH)
        yield FetchedPage(page_index=0, request_params={}, payload=payload)

    def filtered_usage_events_pages(
        self,
        start: datetime,
        end: datetime,
        *,
        page_size: int = MAX_PAGE_SIZE,
        include_included_in_business: bool = True,
    ) -> Iterator[FetchedPage]:
        if start >= end:
            raise ValueError("window start must be before window end")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        end = min(end, datetime.now(UTC))
        if start >= end:
            return
        page_number = 1
        while True:
            if page_number > MAX_PAGES:
                raise CursorApiError(f"the provider kept paging past {MAX_PAGES} pages")
            body = {
                "startDate": epoch_milliseconds(start),
                "endDate": epoch_milliseconds(end - timedelta(milliseconds=1)),
                "page": page_number,
                "pageSize": page_size,
            }
            payload = self._request("POST", FILTERED_USAGE_EVENTS_PATH, body)
            page = FetchedPage(
                page_index=page_number - 1,
                request_params={
                    **body,
                    "_costura_include_included_in_business": include_included_in_business,
                },
                payload=payload,
            )
            yield page
            pagination = payload.get("pagination")
            has_next = (
                pagination.get("hasNextPage")
                if isinstance(pagination, dict)
                else len(page.results) == page_size
            )
            if has_next is not True:
                return
            page_number += 1

    def daily_usage_pages(
        self, start: datetime, end: datetime, *, page_size: int = MAX_PAGE_SIZE
    ) -> Iterator[FetchedPage]:
        if start >= end:
            raise ValueError("window start must be before window end")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        page_index = 0
        window_start = start
        while window_start < end:
            window_end = min(end, window_start + timedelta(days=MAX_WINDOW_DAYS))
            page_number = 1
            while True:
                body = {
                    "startDate": epoch_milliseconds(window_start),
                    "endDate": epoch_milliseconds(window_end - timedelta(milliseconds=1)),
                    "page": page_number,
                    "pageSize": page_size,
                }
                payload = self._request("POST", DAILY_USAGE_PATH, body)
                page = FetchedPage(
                    page_index=page_index,
                    request_params=body,
                    payload=payload,
                )
                yield page
                page_index += 1
                pagination = payload.get("pagination")
                if not isinstance(pagination, dict) or pagination.get("hasNextPage") is not True:
                    break
                page_number += 1
            window_start = window_end

    def spend_pages(self, *, include_included_in_business: bool) -> Iterator[FetchedPage]:
        page_number = 1
        while True:
            body = {"page": page_number, "pageSize": MAX_PAGE_SIZE}
            payload = self._request("POST", SPEND_PATH, body)
            yield FetchedPage(
                page_index=page_number - 1,
                request_params={
                    **body,
                    "_costura_control_field": (
                        "overallSpendCents" if include_included_in_business else "spendCents"
                    ),
                },
                payload=payload,
            )
            total_pages = payload.get("totalPages")
            if isinstance(total_pages, bool) or not isinstance(total_pages, int):
                return
            if page_number >= total_pages:
                return
            page_number += 1

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._http.send(method, path, json=body)


__all__ = [
    "DAILY_USAGE_PATH",
    "SPEND_PATH",
    "CursorAdminClient",
    "CursorApiError",
    "CursorAuthError",
    "FetchedPage",
    "allow_cursor",
    "epoch_milliseconds",
]
