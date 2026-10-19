"""Sample stand-in for the cursor client; see `costura.demo.clients`."""

from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from costura.demo.clients.base import EVENTS_PER_PAGE, SampleClient, _chunks, _millis
from costura.demo.payloads import (
    CursorLedger,
)
from costura.providers.cursor.client import CursorApiError
from costura.providers.cursor.client import FetchedPage as CursorPage


class CursorSampleClient(SampleClient):
    label = "Cursor"
    api_error = CursorApiError

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.ledger = CursorLedger(self.account, self.version)

    def members_pages(self) -> Iterator[CursorPage]:
        yield CursorPage(
            page_index=0,
            request_params={},
            payload={
                "teamMembers": [
                    {
                        "id": u.external_id,
                        "name": u.name,
                        "email": u.email,
                        "role": u.role,
                        "isRemoved": False,
                    }
                    for u in self.users()
                ]
            },
        )

    def filtered_usage_events_pages(
        self,
        start: datetime,
        end: datetime,
        *,
        include_included_in_business: bool = True,
    ) -> Iterator[CursorPage]:
        self._check("filtered_usage_events_pages")
        events = [
            event.row
            for day in self._days(start, end)
            for event in self.ledger.events(day)
            if include_included_in_business or event.kind != "Included in Business"
        ]
        pages = _chunks(events, EVENTS_PER_PAGE)
        for index, rows in enumerate(pages):
            yield CursorPage(
                page_index=index,
                request_params={
                    "startDate": int(start.timestamp() * 1000),
                    "endDate": int(end.timestamp() * 1000) - 1,
                    "page": index + 1,
                    "pageSize": EVENTS_PER_PAGE,
                    "_costura_include_included_in_business": include_included_in_business,
                },
                payload={
                    "totalUsageEventsCount": len(events),
                    "pagination": {
                        "numPages": len(pages),
                        "currentPage": index + 1,
                        "pageSize": EVENTS_PER_PAGE,
                        "hasNextPage": index < len(pages) - 1,
                        "hasPreviousPage": index > 0,
                    },
                    "usageEvents": list(rows),
                },
            )

    def daily_usage_pages(self, start: datetime, end: datetime) -> Iterator[CursorPage]:
        self._check("daily_usage_pages")
        days = self._days(start, end)
        for index, chunk in enumerate(_chunks(days, 30)):
            rows = [
                {"day": day.isoformat(), "email": u.email, "isActive": True}
                for day in chunk
                for u in self.account.users
                if u.added_at <= day
            ]
            yield CursorPage(
                page_index=index,
                request_params={
                    "startDate": _millis(chunk[0]) if chunk else int(start.timestamp() * 1000),
                    "endDate": _millis(chunk[-1] + timedelta(days=1)) - 1
                    if chunk
                    else int(end.timestamp() * 1000) - 1,
                    "page": 1,
                    "pageSize": EVENTS_PER_PAGE,
                },
                payload={"data": rows, "pagination": {"hasNextPage": False}},
            )

    def spend_pages(self, *, include_included_in_business: bool) -> Iterator[CursorPage]:
        self._check("spend_pages")
        cycle = self.as_of.replace(day=1)
        spend: dict[str, Decimal] = {}
        included: dict[str, Decimal] = {}
        cursor = cycle
        while cursor < self.as_of:
            for event in self.ledger.events(cursor):
                bucket = included if event.kind == "Included in Business" else spend
                bucket[event.email] = bucket.get(event.email, Decimal("0")) + event.cents
            cursor += timedelta(days=1)
        yield CursorPage(
            page_index=0,
            request_params={
                "page": 1,
                "pageSize": EVENTS_PER_PAGE,
                "_costura_control_field": (
                    "overallSpendCents" if include_included_in_business else "spendCents"
                ),
            },
            payload={
                "teamMemberSpend": [
                    {
                        "email": u.email,
                        "monthlyLimitDollars": None,
                        "hardLimitOverrideDollars": None,
                        "effectivePerUserLimitDollars": 500,
                        "spendCents": float(spend.get(u.email, Decimal("0"))),
                        "includedSpendCents": float(included.get(u.email, Decimal("0"))),
                    }
                    for u in self.users()
                ],
                "subscriptionCycleStart": _millis(cycle),
                "totalPages": 1,
            },
        )
