"""Sample stand-in for the openrouter client; see `costura.demo.clients`."""

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from costura.demo.clients.base import DAYS_PER_PAGE, SampleClient, _chunks, _iso
from costura.demo.manifest import (
    OPENROUTER_LATE_USAGE,
)
from costura.demo.payloads import (
    OpenRouterDay,
    openrouter_day,
    openrouter_total_row,
)
from costura.providers.openrouter.client import FetchedPage as OpenRouterPage
from costura.providers.openrouter.client import OpenRouterApiError


class OpenRouterSampleClient(SampleClient):
    label = "OpenRouter"
    api_error = OpenRouterApiError

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._cache: dict[date, OpenRouterDay] = {}
        self._names = {k.external_id: k.name for k in self.account.keys}

    def _day(self, day: date) -> OpenRouterDay:
        if day not in self._cache:
            self._cache[day] = openrouter_day(self.account, self.version, day, self._names)
        return self._cache[day]

    def _analytics(
        self, start: datetime, end: datetime, dimensions: list[str], rows: Any
    ) -> Iterator[OpenRouterPage]:
        for index, days in enumerate(_chunks(self._days(start, end), DAYS_PER_PAGE)):
            window_start = days[0] if days else start.date()
            window_end = days[-1] + timedelta(days=1) if days else end.date()
            data = [row for day in days for row in rows(day)]
            yield OpenRouterPage(
                page_index=index,
                request_params={
                    "metrics": [
                        "total_usage",
                        "credits_usage",
                        "byok_usage",
                        "tokens_prompt",
                        "tokens_completion",
                        "cached_tokens",
                        "reasoning_tokens",
                        "request_count",
                    ],
                    "dimensions": dimensions,
                    "granularity": "day",
                    "time_range": {"start": _iso(window_start), "end": _iso(window_end)},
                    "limit": 10000,
                },
                payload={
                    "data": {
                        "data": data,
                        "metadata": {"row_count": len(data), "truncated": False},
                    }
                },
            )

    def analytics_cost_pages(self, start: datetime, end: datetime) -> Iterator[OpenRouterPage]:
        self._check("analytics_cost_pages")
        return self._analytics(start, end, ["api_key_id", "model"], lambda d: self._day(d).rows)

    def analytics_total_pages(self, start: datetime, end: datetime) -> Iterator[OpenRouterPage]:
        self._check("analytics_total_pages")
        last = self.as_of - timedelta(days=1)

        def rows(day: date) -> list[dict[str, Any]]:
            totals = self._day(day)
            if not totals.rows:
                return []
            late = OPENROUTER_LATE_USAGE if day == last else Decimal("0")
            return [openrouter_total_row(day, totals, late)]

        return self._analytics(start, end, [], rows)

    def keys_pages(self) -> Iterator[OpenRouterPage]:
        yield OpenRouterPage(
            page_index=0,
            request_params={"include_disabled": "true", "offset": "0"},
            payload={
                "data": [
                    {
                        "hash": k.external_id,
                        "name": k.name,
                        "label": f"sk-or-v1-...{k.external_id[-4:]}",
                        "disabled": k.status == "disabled",
                        "created_at": f"{k.created_at.isoformat()}T00:00:00.000Z",
                        "updated_at": None,
                        "expires_at": None,
                        "creator_user_id": None,
                        "workspace_id": k.workspace,
                    }
                    for k in self.keys()
                ]
            },
        )

    def workspaces_pages(self) -> Iterator[OpenRouterPage]:
        items = [
            {
                "id": w.external_id,
                "name": w.name,
                "slug": w.name.lower(),
                "created_at": f"{w.created_at.isoformat()}T00:00:00.000Z",
            }
            for w in self.workspaces()
        ]
        yield OpenRouterPage(
            page_index=0, request_params={}, payload={"data": items, "total_count": len(items)}
        )

    def workspace_members_pages(self, workspace_id: str) -> Iterator[OpenRouterPage]:
        self._refuse(403, f"/workspaces/{workspace_id}/members")
        yield from ()

    def organization_members_pages(self) -> Iterator[OpenRouterPage]:
        self._refuse(404, "/organization/members")
        yield from ()
