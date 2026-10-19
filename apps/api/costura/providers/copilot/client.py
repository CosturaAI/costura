"""Read-only client for GitHub's organization billing usage and Copilot seat endpoints.

Every call is a GET with a bearer token and `X-GitHub-Api-Version`. The usage endpoints
take a calendar day (`year`, `month`, `day`) and return the whole day in one response, so a
window becomes one request per day; per-user AI credits add one request per user per day.
Endpoints and fields follow the REST reference read on 2026-10-11; the SKU strings a live
organization returns are not documented and are stored as received.
"""

import re
import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from costura.providers.http import (
    ProviderApiError,
    ProviderAuthError,
    ProviderHttpClient,
)
from costura.providers.pages import FetchedPage as BasePage

DEFAULT_BASE_URL = "https://api.github.com"
API_VERSION = "2026-03-10"
USAGE_PATH = "/organizations/{org}/settings/billing/usage"
AI_CREDIT_PATH = "/organizations/{org}/settings/billing/ai_credit/usage"
SEATS_PATH = "/orgs/{org}/copilot/billing/seats"
BUDGETS_PATH = "/organizations/{org}/settings/billing/budgets"
BUDGETS_PAGE_SIZE = 100
USER_PATH = "/users/{login}"
SEATS_PAGE_SIZE = 100
# The usage endpoints keep 24 months.
MAX_LOOKBACK_DAYS = 24 * 31


class CopilotApiError(ProviderApiError):
    pass


class CopilotAuthError(CopilotApiError, ProviderAuthError):
    """401 or 403: the token is invalid, lacks billing read access, or the organization is
    not visible to it."""


def allow_copilot(request: httpx.Request) -> bool:
    return request.method == "GET"


class FetchedPage(BasePage):
    """Usage pages carry `usageItems`; the seat listing carries `seats`."""

    @property
    def results(self) -> list[dict[str, Any]]:
        rows = self.payload.get("usageItems", [])
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    @property
    def items(self) -> list[dict[str, Any]]:
        rows = self.payload.get("seats", [])
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


class BudgetPage(BasePage):
    @property
    def results(self) -> list[dict[str, Any]]:
        return self.items

    @property
    def items(self) -> list[dict[str, Any]]:
        rows = self.payload.get("budgets", [])
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


GITHUB_LOGIN = re.compile(r"^[A-Za-z0-9-]{1,39}$")


def validate_org(value: str) -> str:
    """A GitHub organization login: letters, digits and hyphens, at most 39 characters."""
    cleaned = value.strip().strip("/")
    if GITHUB_LOGIN.fullmatch(cleaned) is None:
        raise ValueError("the GitHub organization is its login, such as acme-inc")
    return cleaned


def days_in(start: datetime, end: datetime, *, now: datetime | None = None) -> list[date]:
    """The UTC calendar days of `[start, end)`, within the API's lookback and not after today."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    today = (now or datetime.now(UTC)).astimezone(UTC).date()
    first = max(start.astimezone(UTC).date(), today - timedelta(days=MAX_LOOKBACK_DAYS))
    last = min((end.astimezone(UTC) - timedelta(microseconds=1)).date(), today)
    days: list[date] = []
    current = first
    while current <= last:
        days.append(current)
        current += timedelta(days=1)
    return days


class GitHubBillingClient:
    def __init__(
        self,
        *,
        token: str,
        org: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.org = validate_org(org)
        self._http = ProviderHttpClient(
            base_url=base_url,
            headers={
                "authorization": f"Bearer {token}",
                "accept": "application/vnd.github+json",
                "x-github-api-version": API_VERSION,
            },
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
            sleep=sleep,
            label="GitHub Copilot",
            api_error=CopilotApiError,
            auth_error=CopilotAuthError,
            allow=allow_copilot,
        )

    def __enter__(self) -> GitHubBillingClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def seats_pages(self) -> Iterator[FetchedPage]:
        page_number = 1
        while True:
            params = httpx.QueryParams({"page": page_number, "per_page": SEATS_PAGE_SIZE})
            payload = self._http.get(SEATS_PATH.format(org=self.org), params)
            page = FetchedPage(
                page_index=page_number - 1, request_params=dict(params), payload=payload
            )
            yield page
            if len(page.items) < SEATS_PAGE_SIZE:
                return
            page_number += 1

    def budgets_pages(self) -> Iterator[BudgetPage]:
        page_number = 1
        while True:
            params = httpx.QueryParams({"page": page_number, "per_page": BUDGETS_PAGE_SIZE})
            payload = self._http.get(BUDGETS_PATH.format(org=self.org), params)
            yield BudgetPage(
                page_index=page_number - 1, request_params=dict(params), payload=payload
            )
            if payload.get("has_next_page") is not True:
                return
            page_number += 1

    def usage_pages(self, start: datetime, end: datetime) -> Iterator[FetchedPage]:
        """One page per day: every product's usage of the organization on that day."""
        for index, day in enumerate(days_in(start, end)):
            params = httpx.QueryParams({"year": day.year, "month": day.month, "day": day.day})
            payload = self._http.get(USAGE_PATH.format(org=self.org), params)
            yield FetchedPage(
                page_index=index,
                request_params={**dict(params), "_costura_day": day.isoformat()},
                payload=payload,
            )

    def ai_credit_pages(
        self, start: datetime, end: datetime, logins: list[str]
    ) -> Iterator[FetchedPage]:
        """One page per day and login: that user's AI credit usage on that day. The call
        count is days x logins; the window is kept to one month by the scheduler."""
        index = 0
        for day in days_in(start, end):
            for login in logins:
                params = httpx.QueryParams(
                    {"year": day.year, "month": day.month, "day": day.day, "user": login}
                )
                payload = self._http.get(AI_CREDIT_PATH.format(org=self.org), params)
                yield FetchedPage(
                    page_index=index,
                    request_params={
                        **dict(params),
                        "_costura_day": day.isoformat(),
                        "_costura_login": login,
                    },
                    payload=payload,
                )
                index += 1

    def user(self, login: str) -> dict[str, Any]:
        return self._http.get(USER_PATH.format(login=login), httpx.QueryParams())


__all__ = [
    "AI_CREDIT_PATH",
    "API_VERSION",
    "BUDGETS_PATH",
    "SEATS_PATH",
    "USAGE_PATH",
    "USER_PATH",
    "BudgetPage",
    "CopilotApiError",
    "CopilotAuthError",
    "FetchedPage",
    "GitHubBillingClient",
    "allow_copilot",
    "days_in",
    "validate_org",
]
