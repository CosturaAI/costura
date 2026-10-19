"""Read-only client for the Codex Enterprise Analytics API."""

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx

from costura.providers.http import (
    ProviderApiError,
    ProviderAuthError,
    ProviderHttpClient,
)
from costura.providers.pages import FetchedPage as BasePage
from costura.providers.pagination import clamped_windows, cursor_pages

# Verified 2026-09-18 against OpenAI Admin API OpenAPI 2.5.25:
# https://chatgpt.com/public/admin/api-reference/openapi.json
USAGE_PATH = "/workspaces/{workspace_id}/usage"
MAX_LOOKBACK_DAYS = 90
PAGE_LIMIT = 1000


class CodexApiError(ProviderApiError):
    pass


class CodexAuthError(CodexApiError, ProviderAuthError):
    """The Admin API key is invalid or lacks `codex.enterprise.analytics.read`."""


class FetchedPage(BasePage):
    """Analytics rows are the objects in `data`, as on a listing page."""


def validate_workspace_id(value: str) -> str:
    cleaned = value.strip()
    try:
        UUID(cleaned)
    except ValueError as exc:
        raise ValueError("workspace_id must be a UUID from ChatGPT workspace settings") from exc
    return cleaned


def day_windows(
    start: datetime,
    end: datetime,
    *,
    now: datetime | None = None,
) -> list[tuple[datetime, datetime]]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    return clamped_windows(
        start,
        end,
        days=MAX_LOOKBACK_DAYS,
        earliest=current - timedelta(days=MAX_LOOKBACK_DAYS),
        now=current,
    )


class CodexAnalyticsClient:
    def __init__(
        self,
        *,
        admin_key: str,
        workspace_id: str,
        base_url: str = "https://api.chatgpt.com/v1/analytics/codex",
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.workspace_id = validate_workspace_id(workspace_id)
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
            label="Codex",
            api_error=CodexApiError,
            auth_error=CodexAuthError,
        )
        self._client = self._http.client

    def __enter__(self) -> CodexAnalyticsClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def usage_pages(
        self,
        start: datetime,
        end: datetime,
        *,
        workspace: bool = False,
        limit: int = PAGE_LIMIT,
    ) -> Iterator[FetchedPage]:
        page_index = 0
        path = USAGE_PATH.format(workspace_id=self.workspace_id)
        for window_start, window_end in day_windows(start, end):
            # OpenAPI 2.5.25 fixes rows to daily granularity and omits `group_by`; the Codex
            # integration contract lists it, so the request sends it.
            params: dict[str, str | int] = {
                "start_time": int(window_start.timestamp()),
                "end_time": int(window_end.timestamp()),
                "group_by": "day",
                "limit": limit,
            }
            if workspace:
                params["group"] = "workspace"
            window_params = httpx.QueryParams(params)

            def fetch(
                cursor: str | None, window_params: httpx.QueryParams = window_params
            ) -> tuple[httpx.QueryParams, dict[str, Any]]:
                query = window_params.set("page", cursor) if cursor is not None else window_params
                return query, self._http.get(path, query)

            for page in cursor_pages(
                fetch,
                first_index=page_index,
                api_error=CodexApiError,
                missing_message="analytics page has more data but no next_page",
            ):
                yield FetchedPage(**vars(page))
                page_index = page.page_index + 1


__all__ = [
    "MAX_LOOKBACK_DAYS",
    "PAGE_LIMIT",
    "USAGE_PATH",
    "CodexAnalyticsClient",
    "CodexApiError",
    "CodexAuthError",
    "FetchedPage",
    "day_windows",
    "validate_workspace_id",
]
