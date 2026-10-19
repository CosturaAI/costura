"""OpenRouter client: read-only allowlist, pagination, truncation split, auth errors."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from costura.providers.http import GuardedTransport, ReadOnlyViolation, get_only
from costura.providers.openrouter.client import (
    ANALYTICS_METRICS,
    OpenRouterApiError,
    OpenRouterAuthError,
    OpenRouterManagementClient,
    allow_openrouter,
)
from tests.conftest import openrouter_fixture_handler

NO_SLEEP = lambda _: None  # noqa: E731
START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 9, 1, tzinfo=UTC)


def _client(handler, **kwargs) -> OpenRouterManagementClient:
    return OpenRouterManagementClient(
        management_key="sk-or-v1-test",
        transport=httpx.MockTransport(handler),
        sleep=NO_SLEEP,
        **kwargs,
    )


def test_allowlist_is_get_anywhere_plus_post_analytics_query() -> None:
    base = "https://openrouter.ai/api/v1"
    assert allow_openrouter(httpx.Request("GET", f"{base}/keys"))
    assert allow_openrouter(httpx.Request("POST", f"{base}/analytics/query"))
    assert not allow_openrouter(httpx.Request("POST", f"{base}/keys"))
    assert not allow_openrouter(httpx.Request("PATCH", f"{base}/keys/abc"))
    assert not allow_openrouter(httpx.Request("DELETE", f"{base}/keys/abc"))
    assert not allow_openrouter(httpx.Request("PUT", f"{base}/workspaces/w1/budgets"))
    assert not allow_openrouter(httpx.Request("POST", f"{base}/analytics/query/extra"))
    assert not allow_openrouter(httpx.Request("POST", f"{base}/chat/completions"))


def test_guarded_transport_refuses_before_network_io() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        return httpx.Response(200, json={"data": []})

    client = httpx.Client(
        base_url="https://openrouter.ai/api/v1",
        transport=GuardedTransport(
            httpx.MockTransport(handler), allow=allow_openrouter, label="OpenRouter"
        ),
    )
    for method, path in (
        ("POST", "/keys"),
        ("PATCH", "/keys/abc"),
        ("DELETE", "/keys/abc"),
        ("PUT", "/workspaces/w1/budgets"),
    ):
        with pytest.raises(ReadOnlyViolation, match="read-only"):
            client.request(method, path)
    client.post("/analytics/query", json={})
    client.get("/keys")
    assert calls == ["POST /api/v1/analytics/query", "GET /api/v1/keys"]

    anthropic = httpx.Client(
        base_url="https://api.anthropic.com",
        transport=GuardedTransport(httpx.MockTransport(handler), allow=get_only, label="Anthropic"),
    )
    with pytest.raises(ReadOnlyViolation):
        anthropic.post("/v1/organizations/api_keys")


def test_analytics_pages_send_metrics_dimensions_and_daily_granularity() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return openrouter_fixture_handler(request)

    with _client(handler) as client:
        pages = list(client.analytics_cost_pages(START, END))
        totals = list(client.analytics_total_pages(START, END))

    assert len(pages) == 1 and len(pages[0].results) == 6
    assert pages[0].request_params == bodies[0]
    assert bodies[0]["metrics"] == list(ANALYTICS_METRICS)
    assert {"total_usage", "credits_usage", "byok_usage"} <= set(bodies[0]["metrics"])
    assert bodies[0]["dimensions"] == ["api_key_id", "model"]
    assert bodies[0]["granularity"] == "day"
    assert bodies[0]["time_range"] == {
        "start": "2026-08-01T00:00:00Z",
        "end": "2026-09-01T00:00:00Z",
    }
    assert bodies[1]["dimensions"] == []
    assert len(totals[0].results) == 2


def test_truncated_analytics_response_splits_the_window_by_day() -> None:
    windows: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        start, end = body["time_range"]["start"], body["time_range"]["end"]
        windows.append((start, end))
        days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
        truncated = days > 8
        return httpx.Response(
            200,
            json={
                "data": {
                    "data": [] if truncated else [{"date__day": start[:10], "total_usage": 1}],
                    "metadata": {"query_time_ms": 1, "row_count": 0, "truncated": truncated},
                }
            },
        )

    with _client(handler) as client:
        pages = list(client.analytics_cost_pages(START, END))

    assert windows[0] == ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")
    # 31 days -> 15 + 16 -> 7 + 8 + 8 + 8: four leaves in date order, each under the limit.
    assert [p.request_params["time_range"]["start"] for p in pages] == [
        "2026-08-01T00:00:00Z",
        "2026-08-08T00:00:00Z",
        "2026-08-16T00:00:00Z",
        "2026-08-24T00:00:00Z",
    ]
    assert [p.page_index for p in pages] == [0, 1, 2, 3]


def test_truncated_single_day_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {"data": [], "metadata": {"truncated": True, "row_count": 0}}}
        )

    with _client(handler) as client, pytest.raises(OpenRouterApiError, match="one day"):
        list(client.analytics_cost_pages(START, datetime(2026, 8, 2, tzinfo=UTC)))


def test_keys_pages_follow_offset_until_a_short_page() -> None:
    offsets: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = httpx.QueryParams(request.url.query)
        offsets.append(params.get("offset"))
        assert params.get("include_disabled") == "true"
        offset = int(params.get("offset") or 0)
        count = 100 if offset == 0 else 3
        items = [{"hash": f"h{offset + i}"} for i in range(count)]
        return httpx.Response(200, json={"data": items})

    with _client(handler) as client:
        pages = list(client.keys_pages())

    assert offsets == ["0", "100"]
    assert [len(p.items) for p in pages] == [100, 3]
    assert pages[1].request_params == {"include_disabled": "true", "offset": "100"}


def test_current_key_and_auth_errors() -> None:
    with _client(openrouter_fixture_handler) as client:
        assert client.current_key()["is_management_key"] is True

    def forbidden(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "management key required"}})

    with _client(forbidden) as client, pytest.raises(OpenRouterAuthError) as info:
        client.current_key()
    assert info.value.status_code == 403


def test_retries_on_429_and_honours_retry_after() -> None:
    attempts: list[int] = []
    slept: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(429, headers={"retry-after": "2"})
        return httpx.Response(200, json={"data": {"is_management_key": True}})

    client = OpenRouterManagementClient(
        management_key="k", transport=httpx.MockTransport(handler), sleep=slept.append
    )
    with client:
        assert client.current_key()["is_management_key"] is True
    assert len(attempts) == 3
    assert slept == [2.0, 2.0]


def test_exhausted_429_is_marked_temporarily_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    with _client(handler, max_retries=0) as client, pytest.raises(OpenRouterApiError) as info:
        client.current_key()

    assert info.value.status_code == 429
    assert info.value.unavailable is True
