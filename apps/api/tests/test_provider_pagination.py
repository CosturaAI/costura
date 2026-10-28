"""Window and pagination mechanics shared by provider clients."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from costura.providers import pagination
from costura.providers.http import ProviderApiError
from costura.providers.pagination import clamped_windows, cursor_pages, offset_pages, split_window


class PageError(ProviderApiError):
    pass


def test_split_window_is_consecutive_and_keeps_partial_tail() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=5, hours=3)
    assert split_window(start, end, days=2) == [
        (start, start + timedelta(days=2)),
        (start + timedelta(days=2), start + timedelta(days=4)),
        (start + timedelta(days=4), end),
    ]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2026, 1, 1), datetime(2026, 1, 2, tzinfo=UTC)),
        (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2)),
    ],
)
def test_clamped_windows_requires_timezone_aware_bounds(start: datetime, end: datetime) -> None:
    with pytest.raises(ValueError, match="must be timezone-aware"):
        clamped_windows(start, end, days=1)


@pytest.mark.parametrize("days", [0, -1])
def test_split_window_requires_positive_days(days: int) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="days must be positive"):
        split_window(start, start + timedelta(days=1), days=days)


def test_split_window_requires_ordered_bounds() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="start must be before"):
        split_window(now, now, days=1)


def test_cursor_pages_follows_cursor_and_preserves_indexes() -> None:
    seen: list[str | None] = []

    def fetch(cursor: str | None):
        seen.append(cursor)
        if cursor is None:
            return httpx.QueryParams({"limit": 2}), {"has_more": True, "next": "two"}
        return httpx.QueryParams({"cursor": cursor}), {"has_more": False, "data": []}

    pages = list(cursor_pages(fetch, first_index=4, api_error=PageError, cursor_field="next"))
    assert seen == [None, "two"]
    assert [page.page_index for page in pages] == [4, 5]
    assert pages[1].request_params == {"cursor": "two"}


@pytest.mark.parametrize("next_value", [None, "", 3])
def test_cursor_pages_rejects_missing_next_cursor(next_value: object) -> None:
    def fetch(_cursor: str | None):
        return httpx.QueryParams(), {"has_more": True, "next_page": next_value}

    with pytest.raises(PageError, match="custom missing"):
        list(
            cursor_pages(
                fetch,
                first_index=0,
                api_error=PageError,
                missing_message="custom missing",
            )
        )


def test_offset_pages_fetches_the_empty_page_after_exact_full_page() -> None:
    seen: list[int] = []

    def fetch(offset: int):
        seen.append(offset)
        rows = [{"id": 1}, {"id": 2}] if offset == 0 else []
        return httpx.QueryParams({"offset": offset}), {"data": rows}

    pages = list(offset_pages(fetch, first_index=2, page_size=2, items=lambda p: p["data"]))
    assert seen == [0, 2]
    assert [page.page_index for page in pages] == [2, 3]


def test_cursor_pages_refuses_a_repeated_cursor() -> None:
    def fetch(cursor: str | None):
        return httpx.QueryParams({}), {"has_more": True, "next_page": "same"}

    with pytest.raises(PageError, match="same next_page twice"):
        list(cursor_pages(fetch, first_index=0, api_error=PageError))


def test_cursor_pages_stops_at_the_page_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pagination, "MAX_PAGES", 3)
    counter = iter(range(100))

    def fetch(cursor: str | None):
        return httpx.QueryParams({}), {"has_more": True, "next_page": f"c{next(counter)}"}

    with pytest.raises(PageError, match="past 3 pages"):
        list(cursor_pages(fetch, first_index=0, api_error=PageError))


def test_offset_pages_refuses_a_provider_that_ignores_the_offset() -> None:
    def fetch(offset: int):
        return httpx.QueryParams({"offset": str(offset)}), {"data": [1, 2]}

    with pytest.raises(PageError, match="same page for a new offset"):
        list(
            offset_pages(
                fetch, first_index=0, page_size=2, items=lambda p: p["data"], api_error=PageError
            )
        )
