import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from costura.providers.codex.client import (
    USAGE_PATH,
    CodexAnalyticsClient,
    day_windows,
)

FIXTURE = Path(__file__).parent / "fixtures" / "codex" / "official_usage_page.json"
WORKSPACE_ID = "11111111-2222-4333-8444-555555555555"
NO_SLEEP = lambda _: None  # noqa: E731


def test_usage_uses_bearer_workspace_daily_grain_and_cursor_pagination() -> None:
    requests: list[httpx.Request] = []
    payload = json.loads(FIXTURE.read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("page") is None:
            return httpx.Response(
                200,
                json={**payload, "has_more": True, "next_page": "next-cursor"},
            )
        return httpx.Response(200, json={"object": "page", "data": [], "has_more": False})

    start = datetime(2026, 9, 17, tzinfo=UTC)
    end = datetime(2026, 9, 18, tzinfo=UTC)
    with CodexAnalyticsClient(
        admin_key="redacted",
        workspace_id=WORKSPACE_ID,
        transport=httpx.MockTransport(handler),
        sleep=NO_SLEEP,
    ) as client:
        pages = list(
            client.usage_pages(
                start,
                end,
                workspace=True,
            )
        )

    assert [page.page_index for page in pages] == [0, 1]
    assert requests[0].url.path.endswith(USAGE_PATH.format(workspace_id=WORKSPACE_ID))
    assert requests[0].headers["authorization"] == "Bearer redacted"
    assert requests[0].url.params["group"] == "workspace"
    assert requests[0].url.params["group_by"] == "day"
    assert requests[0].url.params["start_time"] == str(int(start.timestamp()))
    assert requests[0].url.params["end_time"] == str(int(end.timestamp()))
    assert requests[1].url.params["page"] == "next-cursor"


def test_per_user_request_omits_group_and_lookback_is_clamped_to_90_days() -> None:
    request: httpx.Request | None = None

    def handler(value: httpx.Request) -> httpx.Response:
        nonlocal request
        request = value
        return httpx.Response(200, json={"object": "page", "data": [], "has_more": False})

    now = datetime(2026, 9, 18, tzinfo=UTC)
    with CodexAnalyticsClient(
        admin_key="redacted",
        workspace_id=WORKSPACE_ID,
        transport=httpx.MockTransport(handler),
        sleep=NO_SLEEP,
    ) as client:
        list(client.usage_pages(now - timedelta(days=100), now))

    assert request is not None
    assert "group" not in request.url.params
    assert day_windows(now - timedelta(days=100), now, now=now) == [(now - timedelta(days=90), now)]


def test_workspace_id_must_be_a_uuid() -> None:
    with pytest.raises(ValueError, match="workspace_id must be a UUID"):
        CodexAnalyticsClient(admin_key="redacted", workspace_id="workspace-name")


def test_reads_start_at_the_first_whole_day_inside_the_lookback() -> None:
    from costura.providers.codex.client import served_from

    now = datetime(2026, 10, 28, 14, 30, tzinfo=UTC)
    assert served_from(now) == datetime(2026, 7, 31, tzinfo=UTC)
    assert served_from(datetime(2026, 10, 28, tzinfo=UTC)) == datetime(2026, 7, 30, tzinfo=UTC)
    windows = day_windows(
        datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC), now=now
    )
    assert windows[0][0] == datetime(2026, 7, 31, tzinfo=UTC)
