import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from costura.providers.claude_ai.client import (
    COST_GROUP_BY,
    COST_REPORT_PATH,
    ClaudeAiAnalyticsClient,
    day_windows,
)

FIXTURES = Path(__file__).parent / "fixtures" / "claude_ai"
START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 2, 15, tzinfo=UTC)
NO_SLEEP = lambda _: None  # noqa: E731


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_windows_clamp_to_first_available_day_and_31_days() -> None:
    windows = day_windows(datetime(2025, 12, 1, tzinfo=UTC), END)
    assert windows == [
        (START, datetime(2026, 2, 1, tzinfo=UTC)),
        (datetime(2026, 2, 1, tzinfo=UTC), END),
    ]
    assert day_windows(START, START) == []


def test_cost_report_uses_headers_daily_grain_and_all_dimensions() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=fixture("cost_report.json"))

    with ClaudeAiAnalyticsClient(
        api_key="redacted", transport=httpx.MockTransport(handler), sleep=NO_SLEEP
    ) as client:
        pages = list(client.cost_report_pages(START, datetime(2026, 1, 3, tzinfo=UTC)))

    assert len(pages) == 1
    request = requests[0]
    assert request.url.path == COST_REPORT_PATH
    assert request.headers["x-api-key"] == "redacted"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert request.url.params.get("bucket_width") == "1d"
    assert request.url.params.get_list("group_by[]") == list(COST_GROUP_BY)


def test_expired_page_cursor_restarts_once_without_yielding_stale_pages() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        page = request.url.params.get("page")
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "data": [],
                    "data_refreshed_at": "2026-01-02T00:00:00Z",
                    "has_more": True,
                    "next_page": "stale",
                },
            )
        if page == "stale":
            return httpx.Response(410, json={"error": {"message": "cursor expired"}})
        return httpx.Response(
            200,
            json={
                "data": [],
                "data_refreshed_at": "2026-01-02T00:00:00Z",
                "has_more": page is None,
                "next_page": "fresh" if page is None else None,
            },
        )

    with ClaudeAiAnalyticsClient(
        api_key="redacted",
        transport=httpx.MockTransport(handler),
        max_retries=0,
        sleep=NO_SLEEP,
    ) as client:
        pages = list(client.cost_report_pages(START, datetime(2026, 1, 2, tzinfo=UTC)))

    assert calls == 4
    assert [page.page_index for page in pages] == [0, 1]
    assert [page.request_params.get("page") for page in pages] == [None, "fresh"]
