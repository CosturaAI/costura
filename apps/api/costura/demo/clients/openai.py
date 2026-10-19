"""Sample stand-in for the openai client; see `costura.demo.clients`."""

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from costura.demo.clients.base import DAYS_PER_PAGE, SampleClient, _chunks, _unix
from costura.demo.manifest import (
    User,
)
from costura.demo.payloads import (
    OpenAIDay,
    openai_day,
)
from costura.providers.openai.client import FetchedPage as OpenAIPage
from costura.providers.openai.client import OpenAIApiError
from costura.providers.openai.sync import ACTIVITY_FAMILIES


class OpenAISampleClient(SampleClient):
    label = "OpenAI"
    api_error = OpenAIApiError

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._cache: dict[date, OpenAIDay] = {}

    def _day(self, day: date) -> OpenAIDay:
        if day not in self._cache:
            self._cache[day] = openai_day(self.account, self.version, day)
        return self._cache[day]

    def _report(
        self, path: str, start: datetime, end: datetime, group_by: list[str], results: Any
    ) -> Iterator[OpenAIPage]:
        pages = _chunks(self._days(start, end), DAYS_PER_PAGE)
        for index, days in enumerate(pages):
            more = index < len(pages) - 1
            yield OpenAIPage(
                page_index=index,
                request_params={
                    "path": path,
                    "start_time": str(int(start.timestamp())),
                    "end_time": str(int(end.timestamp())),
                    "bucket_width": "1d",
                    "group_by": group_by,
                    **({"page": f"page_{index}"} if index else {}),
                },
                payload={
                    "object": "page",
                    "data": [
                        {
                            "object": "bucket",
                            "start_time": _unix(day),
                            "end_time": _unix(day + timedelta(days=1)),
                            "results": results(self._day(day)),
                        }
                        for day in days
                    ],
                    "has_more": more,
                    "next_page": f"page_{index + 1}" if more else None,
                },
            )

    def costs_pages(self, start: datetime, end: datetime) -> Iterator[OpenAIPage]:
        self._check("costs_pages")
        group_by = ["line_item", "project_id", "api_key_id"]
        return self._report("/organization/costs", start, end, group_by, lambda d: d.cost)

    def costs_total_pages(self, start: datetime, end: datetime) -> Iterator[OpenAIPage]:
        self._check("costs_total_pages")
        return self._report(
            "/organization/costs",
            start,
            end,
            [],
            lambda d: [_openai_money(d.total, None, None)] if d.cost else [],
        )

    def costs_by_key_pages(self, start: datetime, end: datetime) -> Iterator[OpenAIPage]:
        self._check("costs_by_key_pages")
        return self._report(
            "/organization/costs",
            start,
            end,
            ["project_id", "api_key_id"],
            lambda d: [
                _openai_money(amount, project, key)
                for (project, key), amount in sorted(
                    d.by_key.items(), key=lambda item: (str(item[0][0]), str(item[0][1]))
                )
            ],
        )

    def usage_completions_pages(self, start: datetime, end: datetime) -> Iterator[OpenAIPage]:
        self._check("usage_completions_pages")
        group_by = ["project_id", "user_id", "api_key_id", "model"]
        return self._report(
            "/organization/usage/completions", start, end, group_by, lambda d: d.usage
        )

    def usage_family_pages(
        self, family: str, start: datetime, end: datetime
    ) -> Iterator[OpenAIPage]:
        if family not in ACTIVITY_FAMILIES:
            raise ValueError(f"unknown OpenAI usage family: {family!r}")
        self._check(f"usage_{family}")
        return self._report(
            f"/organization/usage/{family}",
            start,
            end,
            ["project_id"],
            lambda d: d.activity.get(family, []),
        )

    def _listing(self, items: list[dict[str, Any]]) -> Iterator[OpenAIPage]:
        yield OpenAIPage(
            page_index=0,
            request_params={"limit": "100"},
            payload={
                "object": "list",
                "data": items,
                "first_id": items[0]["id"] if items else None,
                "last_id": items[-1]["id"] if items else None,
                "has_more": False,
            },
        )

    def projects_pages(self) -> Iterator[OpenAIPage]:
        return self._listing(
            [
                {
                    "object": "organization.project",
                    "id": w.external_id,
                    "name": w.name,
                    "created_at": _unix(w.created_at),
                    "archived_at": _unix(w.archived_at)
                    if w.archived_at and w.archived_at < self.as_of
                    else None,
                    "status": "archived"
                    if w.archived_at and w.archived_at < self.as_of
                    else "active",
                }
                for w in self.workspaces()
            ]
        )

    def _user(self, user: User, role: str | None = None) -> dict[str, Any]:
        return {
            "object": "organization.user",
            "id": user.external_id,
            "name": user.name,
            "email": user.email,
            "role": role or user.role,
            "added_at": _unix(user.added_at),
        }

    def users_pages(self) -> Iterator[OpenAIPage]:
        return self._listing([self._user(u) for u in self.users()])

    def _project(self, project_id: str) -> None:
        workspace = next(w for w in self.account.workspaces if w.external_id == project_id)
        if workspace.refuses_listing is not None:
            self._refuse(workspace.refuses_listing, f"/organization/projects/{project_id}")

    def project_api_keys_pages(self, project_id: str) -> Iterator[OpenAIPage]:
        self._project(project_id)
        users = {u.external_id: u for u in self.users()}
        items = []
        for key in self.keys():
            if key.workspace != project_id:
                continue
            if key.service_account is not None:
                account_id, name = key.service_account
                owner: dict[str, Any] = {
                    "type": "service_account",
                    "service_account": {
                        "object": "organization.project.service_account",
                        "id": account_id,
                        "name": name,
                        "role": "member",
                        "created_at": _unix(key.created_at),
                    },
                }
            else:
                owner = {"type": "user", "user": self._user(users[key.owner or ""])}
            items.append(
                {
                    "object": "organization.project.api_key",
                    "redacted_value": f"sk-proj-...{key.external_id[-4:]}",
                    "name": key.name,
                    "created_at": _unix(key.created_at),
                    "last_used_at": _unix(self.as_of - timedelta(days=1)),
                    "id": key.external_id,
                    "owner": owner,
                }
            )
        return self._listing(items)

    def project_users_pages(self, project_id: str) -> Iterator[OpenAIPage]:
        self._project(project_id)
        users = {u.external_id: u for u in self.users()}
        return self._listing(
            [
                self._user(users[user], role)
                for ws, user, role in self.account.members
                if ws == project_id and user in users
            ]
        )


def _openai_money(amount: Decimal, project: str | None, key: str | None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "object": "organization.costs.result",
        "amount": {"value": float(amount), "currency": "usd"},
        "line_item": None,
        "project_id": project,
    }
    if key is not None or project is not None:
        row["api_key_id"] = key
    return row
