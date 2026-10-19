"""Pagination and window splitting shared by the provider clients.

The iterators page until the provider says there is no more, and raise the provider's own
error class when a page claims more data without naming the next one.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from costura.providers.http import ProviderApiError, params_as_dict
from costura.providers.pages import FetchedPage


def clamped_windows(
    start: datetime,
    end: datetime,
    *,
    days: int,
    earliest: datetime | None = None,
    now: datetime | None = None,
) -> list[tuple[datetime, datetime]]:
    """`[start, end)` clipped to `[earliest, now)` and split into windows of at most `days`
    days; empty when nothing is left. Both bounds must be timezone-aware."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    start = start.astimezone(UTC)
    if earliest is not None:
        start = max(start, earliest)
    end = min(end.astimezone(UTC), current)
    if start >= end:
        return []
    return split_window(start, end, days=days)


def split_window(start: datetime, end: datetime, *, days: int) -> list[tuple[datetime, datetime]]:
    """Split `[start, end)` into consecutive windows of at most `days` days."""
    if start >= end:
        raise ValueError("window start must be before window end")
    if days <= 0:
        raise ValueError("window days must be positive")
    windows: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=days), end)
        windows.append((cursor, chunk_end))
        cursor = chunk_end
    return windows


def cursor_pages(
    fetch: Callable[[str | None], tuple[httpx.QueryParams, dict[str, Any]]],
    *,
    first_index: int,
    api_error: type[ProviderApiError],
    cursor_field: str = "next_page",
    missing_message: str | None = None,
) -> Iterator[FetchedPage]:
    """Pages linked by `has_more` plus the cursor field. `fetch` takes the cursor (None on the
    first page) and returns the query it sent plus the payload."""
    cursor: str | None = None
    index = first_index
    while True:
        query, payload = fetch(cursor)
        yield FetchedPage(index, params_as_dict(query), payload)
        index += 1
        if payload.get("has_more") is not True:
            return
        next_page = payload.get(cursor_field)
        if not isinstance(next_page, str) or not next_page:
            raise api_error(missing_message or f"page has more data but no {cursor_field}")
        cursor = next_page


def offset_pages(
    fetch: Callable[[int], tuple[httpx.QueryParams, dict[str, Any]]],
    *,
    first_index: int,
    page_size: int,
    items: Callable[[dict[str, Any]], list[Any]],
) -> Iterator[FetchedPage]:
    """Pages addressed by an offset that grows by `page_size` until a short page arrives."""
    offset = 0
    index = first_index
    while True:
        query, payload = fetch(offset)
        yield FetchedPage(index, params_as_dict(query), payload)
        index += 1
        if len(items(payload)) < page_size:
            return
        offset += page_size
