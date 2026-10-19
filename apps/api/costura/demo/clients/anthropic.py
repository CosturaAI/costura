"""Sample stand-in for the anthropic client; see `costura.demo.clients`."""

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any

from costura.demo.clients.base import DAYS_PER_PAGE, SampleClient, _chunks, _iso
from costura.demo.payloads import (
    AnthropicDay,
    anthropic_day,
)
from costura.providers.anthropic.client import AnthropicApiError
from costura.providers.anthropic.client import FetchedPage as AnthropicPage


class AnthropicSampleClient(SampleClient):
    label = "Anthropic"
    api_error = AnthropicApiError

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._cache: dict[date, AnthropicDay] = {}

    def _day(self, day: date) -> AnthropicDay:
        if day not in self._cache:
            self._cache[day] = anthropic_day(self.account, self.version, day)
        return self._cache[day]

    def _report(
        self, start: datetime, end: datetime, group_by: list[str], results: Any
    ) -> Iterator[AnthropicPage]:
        pages = _chunks(self._days(start, end), DAYS_PER_PAGE)
        for index, days in enumerate(pages):
            more = index < len(pages) - 1
            yield AnthropicPage(
                page_index=index,
                request_params={
                    "starting_at": _iso(start.date()),
                    "ending_at": _iso(end.date()),
                    "bucket_width": "1d",
                    "group_by[]": group_by,
                    **({"page": f"page_{index}"} if index else {}),
                },
                payload={
                    "data": [
                        {
                            "starting_at": _iso(day),
                            "ending_at": _iso(day + timedelta(days=1)),
                            "results": results(self._day(day)),
                        }
                        for day in days
                    ],
                    "has_more": more,
                    "next_page": f"page_{index + 1}" if more else None,
                },
            )

    def cost_report_pages(self, start: datetime, end: datetime) -> Iterator[AnthropicPage]:
        self._check("cost_report_pages")
        return self._report(start, end, ["workspace_id", "description"], lambda day: day.cost)

    def cost_total_pages(self, start: datetime, end: datetime) -> Iterator[AnthropicPage]:
        self._check("cost_total_pages")
        return self._report(
            start,
            end,
            [],
            lambda day: [{"amount": str(day.total_cents), "currency": "USD"}] if day.cost else [],
        )

    def usage_report_pages(self, start: datetime, end: datetime) -> Iterator[AnthropicPage]:
        self._check("usage_report_pages")
        group_by = ["api_key_id", "account_id", "workspace_id", "model", "service_tier"]
        return self._report(start, end, group_by, lambda day: day.usage)

    def _listing(self, items: list[dict[str, Any]]) -> Iterator[AnthropicPage]:
        yield AnthropicPage(
            page_index=0,
            request_params={"limit": "100"},
            payload={
                "data": items,
                "has_more": False,
                "first_id": items[0].get("id") if items else None,
                "last_id": items[-1].get("id") if items else None,
            },
        )

    def workspaces_pages(self, *, include_archived: bool = True) -> Iterator[AnthropicPage]:
        return self._listing(
            [
                {
                    "id": w.external_id,
                    "type": "workspace",
                    "name": w.name,
                    "created_at": _iso(w.created_at),
                    "archived_at": _iso(w.archived_at)
                    if w.archived_at and w.archived_at < self.as_of
                    else None,
                    "display_color": "#6C5BB9",
                    "tags": {},
                }
                for w in self.workspaces()
                if include_archived or w.archived_at is None
            ]
        )

    def users_pages(self) -> Iterator[AnthropicPage]:
        return self._listing(
            [
                {
                    "id": u.external_id,
                    "type": "user",
                    "email": u.email,
                    "name": u.name,
                    "role": u.role,
                    "added_at": _iso(u.added_at),
                }
                for u in self.users()
            ]
        )

    def api_keys_pages(self) -> Iterator[AnthropicPage]:
        return self._listing(
            [
                {
                    "id": k.external_id,
                    "type": "api_key",
                    "name": k.name,
                    "workspace_id": k.workspace,
                    "created_at": _iso(k.created_at),
                    "created_by": {"id": k.owner, "type": "user"},
                    "principal": {"id": k.owner, "type": "user"},
                    "partial_key_hint": f"sk-ant-api03-...{k.external_id[-4:]}",
                    "status": k.status
                    if k.expires_at is None or k.expires_at < self.as_of
                    else "active",
                    "expires_at": _iso(k.expires_at) if k.expires_at else None,
                }
                for k in self.keys()
            ]
        )

    def workspace_members_pages(self, workspace_id: str) -> Iterator[AnthropicPage]:
        workspace = next(w for w in self.account.workspaces if w.external_id == workspace_id)
        if workspace.refuses_listing is not None:
            self._refuse(workspace.refuses_listing, f"/v1/organizations/workspaces/{workspace_id}")
        users = {u.external_id for u in self.users()}
        return self._listing(
            [
                {
                    "type": "workspace_member",
                    "user_id": user,
                    "workspace_id": workspace_id,
                    "workspace_role": role,
                }
                for ws, user, role in self.account.members
                if ws == workspace_id and user in users
            ]
        )
