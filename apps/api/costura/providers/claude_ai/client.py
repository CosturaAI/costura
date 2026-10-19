"""Read-only client for the Claude.ai Enterprise Analytics API."""

import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any

import httpx

from costura.providers.http import (
    ProviderApiError,
    ProviderAuthError,
    ProviderHttpClient,
    params_as_dict,
)
from costura.providers.normalization import rfc3339
from costura.providers.pages import FetchedPage as BasePage
from costura.providers.pagination import clamped_windows

ANTHROPIC_VERSION = "2023-06-01"
EARLIEST = datetime(2026, 1, 1, tzinfo=UTC)
MAX_DAYS = 31
REPORT_LIMIT = 31
USER_LIMIT = 1000

COST_REPORT_PATH = "/v1/organizations/analytics/cost_report"
USER_COST_REPORT_PATH = "/v1/organizations/analytics/user_cost_report"
USER_USAGE_REPORT_PATH = "/v1/organizations/analytics/user_usage_report"
USERS_PATH = "/v1/organizations/analytics/users"

COST_GROUP_BY = (
    "product",
    "model",
    "cost_type",
    "token_type",
    "speed",
    "context_window",
    "inference_geo",
)
USER_GROUP_BY = ("product", "model")


class ClaudeAiApiError(ProviderApiError):
    pass


class ClaudeAiAuthError(ClaudeAiApiError, ProviderAuthError):
    """The analytics key is invalid or lacks `read:analytics`."""


class FetchedPage(BasePage):
    @property
    def results(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for bucket in self.payload.get("data", []):
            if isinstance(bucket, dict) and isinstance(bucket.get("results"), list):
                results.extend(item for item in bucket["results"] if isinstance(item, dict))
            elif isinstance(bucket, dict):
                results.append(bucket)
        return results


def day_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    return clamped_windows(start, end, days=MAX_DAYS, earliest=EARLIEST)


class ClaudeAiAnalyticsClient:
    def __init__(
        self,
        *,
        api_key: str,
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
                "x-api-key": api_key,
            },
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
            sleep=sleep,
            label="Claude.ai",
            api_error=ClaudeAiApiError,
            auth_error=ClaudeAiAuthError,
        )
        self._client = self._http.client

    def __enter__(self) -> ClaudeAiAnalyticsClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def cost_report_pages(self, start: datetime, end: datetime) -> Iterator[FetchedPage]:
        return self._report_pages(COST_REPORT_PATH, start, end, COST_GROUP_BY)

    def cost_total_pages(self, start: datetime, end: datetime) -> Iterator[FetchedPage]:
        return self._report_pages(COST_REPORT_PATH, start, end, ())

    def user_report_pages(self, start: datetime, end: datetime) -> Iterator[FetchedPage]:
        page_index = 0
        for kind, path in (
            ("cost", USER_COST_REPORT_PATH),
            ("usage", USER_USAGE_REPORT_PATH),
        ):
            for page in self._report_pages(path, start, end, USER_GROUP_BY, first_index=page_index):
                yield FetchedPage(
                    page_index=page.page_index,
                    request_params={**page.request_params, "report_kind": kind},
                    payload=page.payload,
                )
                page_index = page.page_index + 1

    def users_pages(
        self, *, activity_date: date | None = None, limit: int = USER_LIMIT
    ) -> Iterator[FetchedPage]:
        if activity_date is None:
            params = [
                ("starting_date", EARLIEST.date().isoformat()),
                ("ending_date", datetime.now(UTC).date().isoformat()),
                ("limit", str(limit)),
            ]
        else:
            activity_date = max(activity_date, EARLIEST.date())
            params = [("date", activity_date.isoformat()), ("limit", str(limit))]
        yield from self._opaque_pages(USERS_PATH, params, first_index=0)

    def _report_pages(
        self,
        path: str,
        start: datetime,
        end: datetime,
        group_by: tuple[str, ...],
        *,
        first_index: int = 0,
    ) -> Iterator[FetchedPage]:
        page_index = first_index
        for window_start, window_end in day_windows(start, end):
            params = [
                ("starting_at", rfc3339(window_start)),
                ("ending_at", rfc3339(window_end)),
                ("bucket_width", "1d"),
                ("limit", str(REPORT_LIMIT if path == COST_REPORT_PATH else USER_LIMIT)),
            ]
            params.extend(("group_by[]", dimension) for dimension in group_by)
            for page in self._opaque_pages(path, params, first_index=page_index):
                yield page
                page_index = page.page_index + 1

    def _opaque_pages(
        self, path: str, params: list[tuple[str, str]], *, first_index: int
    ) -> Iterator[FetchedPage]:
        restarted = False
        while True:
            query = httpx.QueryParams(tuple(params))
            buffered: list[tuple[dict[str, Any], dict[str, Any]]] = []
            try:
                while True:
                    payload = self._http.get(path, query)
                    buffered.append((params_as_dict(query), payload))
                    next_page = payload.get("next_page")
                    has_more = payload.get("has_more")
                    if has_more is not True and not (
                        path == USERS_PATH and isinstance(next_page, str) and next_page
                    ):
                        break
                    if not isinstance(next_page, str) or not next_page:
                        raise ClaudeAiApiError("analytics page has more data but no next_page")
                    query = query.set("page", next_page)
            except ClaudeAiApiError as exc:
                if exc.status_code != 410 or restarted:
                    raise
                restarted = True
                continue
            for offset, (request_params, payload) in enumerate(buffered):
                yield FetchedPage(first_index + offset, request_params, payload)
            return


__all__ = [
    "ClaudeAiAnalyticsClient",
    "ClaudeAiApiError",
    "ClaudeAiAuthError",
    "FetchedPage",
    "day_windows",
]
