"""The shared paging and failure behaviour of the sample provider clients."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from costura.demo.manifest import (
    Account,
    Key,
    User,
    Workspace,
)
from costura.providers.http import ProviderApiError

DAYS_PER_PAGE = 7
EVENTS_PER_PAGE = 500


def _chunks[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)] or [items[:0]]


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _iso(day: date) -> str:
    return f"{day.isoformat()}T00:00:00Z"


def _unix(day: date) -> int:
    return int(_midnight(day).timestamp())


def _millis(day: date) -> int:
    return _unix(day) * 1000


class SampleClient:
    label = "Provider"
    api_error: type[ProviderApiError] = ProviderApiError

    def __init__(
        self,
        account: Account,
        version: int,
        as_of: date,
        *,
        failures: dict[str, int] | None = None,
    ) -> None:
        self.account = account
        self.version = version
        self.as_of = as_of
        self._failures = dict(failures or {})

    def __enter__(self) -> SampleClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        return None

    def _check(self, call: str) -> None:
        remaining = self._failures.get(call, 0)
        if remaining > 0:
            self._failures[call] = remaining - 1
            public = f"{self.label} answered HTTP 503 (service unavailable)"
            raise self.api_error(public, status_code=503, unavailable=True, public=public)

    def _refuse(self, status: int, path: str) -> None:
        public = f"{self.label} answered HTTP {status} on {path}"
        raise self.api_error(public, status_code=status, public=public)

    def _days(self, start: datetime, end: datetime) -> list[date]:
        days = []
        cursor = start.date()
        last = min(end.date(), self.as_of)
        while cursor < last:
            days.append(cursor)
            cursor += timedelta(days=1)
        return days

    def _existing(self, created: date) -> bool:
        return created < self.as_of

    def workspaces(self) -> list[Workspace]:
        return [w for w in self.account.workspaces if self._existing(w.created_at)]

    def users(self) -> list[User]:
        return [u for u in self.account.users if self._existing(u.added_at)]

    def keys(self) -> list[Key]:
        return [k for k in self.account.keys if self._existing(k.created_at)]
