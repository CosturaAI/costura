import json
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

import costura
from costura.providers.anthropic.client import (
    AnthropicAdminClient,
    AnthropicApiError,
    AnthropicAuthError,
    day_windows,
    rfc3339,
)
from costura.providers.http import ReadOnlyViolation

START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 9, 1, tzinfo=UTC)


def _page(has_more: bool, next_page: str | None, marker: str) -> dict:
    return {
        "data": [{"starting_at": marker, "ending_at": marker, "results": []}],
        "has_more": has_more,
        "next_page": next_page,
    }


def _client(handler, sleeps: list[float] | None = None, **kwargs) -> AnthropicAdminClient:
    return AnthropicAdminClient(
        admin_key="sk-ant-admin01-test",
        transport=httpx.MockTransport(handler),
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
        **kwargs,
    )


def test_rfc3339_is_utc_with_z_suffix() -> None:
    assert rfc3339(datetime(2026, 8, 1, tzinfo=UTC)) == "2026-08-01T00:00:00Z"
    with pytest.raises(ValueError):
        rfc3339(datetime(2026, 8, 1))


def test_day_windows_splits_at_31_days() -> None:
    windows = day_windows(START, datetime(2026, 9, 15, tzinfo=UTC))

    assert windows == [
        (START, datetime(2026, 9, 1, tzinfo=UTC)),
        (datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 15, tzinfo=UTC)),
    ]
    assert day_windows(START, END) == [(START, END)]
    with pytest.raises(ValueError):
        day_windows(END, START)


def test_headers_and_query_for_cost_report() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_page(False, None, "a"))

    with _client(handler) as client:
        pages = list(client.cost_report_pages(START, END))

    request = seen[0]
    assert request.headers["x-api-key"] == "sk-ant-admin01-test"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert request.url.path == "/v1/organizations/cost_report"
    params = httpx.QueryParams(request.url.query)
    assert params["starting_at"] == "2026-08-01T00:00:00Z"
    assert params["ending_at"] == "2026-09-01T00:00:00Z"
    assert params["bucket_width"] == "1d"
    assert params["limit"] == "31"
    assert params.get_list("group_by[]") == ["workspace_id", "description"]
    assert pages[0].request_params["group_by[]"] == ["workspace_id", "description"]
    assert pages[0].page_index == 0


def test_usage_report_group_by_stays_within_api_limit_and_slices_by_filters() -> None:
    seen: list[tuple[list[str], str | None, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/organizations/usage_report/messages"
        params = httpx.QueryParams(request.url.query)
        group_by = params.get_list("group_by[]")
        assert len(group_by) <= 5
        seen.append((group_by, params.get("context_window[]"), params.get("inference_geos[]")))
        return httpx.Response(200, json=_page(False, None, "a"))

    with _client(handler) as client:
        pages = list(client.usage_report_pages(START, END))

    assert len(pages) == 6
    assert [page.page_index for page in pages] == list(range(6))
    assert all(
        g == ["api_key_id", "account_id", "workspace_id", "model", "service_tier"]
        for g, _, _ in seen
    )
    assert sorted((w, geo) for _, w, geo in seen) == [
        ("0-200k", "global"),
        ("0-200k", "not_available"),
        ("0-200k", "us"),
        ("200k-1M", "global"),
        ("200k-1M", "not_available"),
        ("200k-1M", "us"),
    ]
    assert pages[0].request_params["context_window[]"] == "0-200k"
    assert pages[0].request_params["inference_geos[]"] == "global"


def test_non_retryable_error_includes_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "Cannot specify more than 5 `group_by[]` dimensions."}},
            headers={"request-id": "req_test"},
        )

    with _client(handler) as client, pytest.raises(AnthropicApiError) as info:
        list(client.cost_report_pages(START, END))

    assert "status=400" in str(info.value)
    assert "request_id=req_test" in str(info.value)
    assert "more than 5" in str(info.value)
    assert info.value.unavailable is False


def test_pagination_follows_next_page_until_has_more_false() -> None:
    pages_by_cursor = {
        None: _page(True, "cursor-1", "p0"),
        "cursor-1": _page(True, "cursor-2", "p1"),
        "cursor-2": _page(False, None, "p2"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = httpx.QueryParams(request.url.query).get("page")
        return httpx.Response(200, json=pages_by_cursor[cursor])

    with _client(handler) as client:
        pages = list(client.cost_report_pages(START, END))

    assert [p.page_index for p in pages] == [0, 1, 2]
    assert [p.payload["data"][0]["starting_at"] for p in pages] == ["p0", "p1", "p2"]
    assert pages[1].request_params["page"] == "cursor-1"
    assert "page" not in pages[0].request_params


def test_window_over_31_days_issues_one_request_per_chunk() -> None:
    windows: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = httpx.QueryParams(request.url.query)
        windows.append((params["starting_at"], params["ending_at"]))
        return httpx.Response(200, json=_page(False, None, "a"))

    with _client(handler) as client:
        pages = list(client.cost_report_pages(START, datetime(2026, 9, 15, tzinfo=UTC)))

    assert windows == [
        ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"),
        ("2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z"),
    ]
    assert [p.page_index for p in pages] == [0, 1]


def test_429_with_retry_after_is_retried_then_succeeds() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"retry-after": "2"}, json={"error": "rate"})
        return httpx.Response(200, json=_page(False, None, "a"))

    with _client(handler, sleeps) as client:
        pages = list(client.cost_report_pages(START, END))

    assert attempts == 2
    assert sleeps == [2.0]
    assert len(pages) == 1


def test_retry_after_is_capped_at_30_seconds() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"retry-after": "120"})
        return httpx.Response(200, json=_page(False, None, "a"))

    with _client(handler, sleeps) as client:
        list(client.cost_report_pages(START, END))

    assert sleeps == [30.0]


def test_5xx_exhausts_retries_and_raises() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"error": "down"})

    with (
        _client(handler, sleeps, max_retries=2) as client,
        pytest.raises(AnthropicApiError) as excinfo,
    ):
        list(client.cost_report_pages(START, END))

    assert attempts == 3
    assert sleeps == [1.0, 2.0]
    assert excinfo.value.status_code == 503
    assert excinfo.value.unavailable is True


def test_401_raises_auth_error_without_retry() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, headers={"request-id": "req_1"}, json={"error": "auth"})

    with _client(handler) as client, pytest.raises(AnthropicAuthError, match="request_id=req_1"):
        list(client.cost_report_pages(START, END))

    assert attempts == 1


def test_has_more_without_next_page_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"data": [], "has_more": True}))

    with _client(handler) as client, pytest.raises(AnthropicApiError, match="no next_page"):
        list(client.cost_report_pages(START, END))


def test_transport_rejects_non_get_before_network() -> None:
    reached: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        reached.append(request.method)
        return httpx.Response(200, json={})

    with _client(handler) as client:
        with pytest.raises(ReadOnlyViolation, match="read-only"):
            client._client.post("/v1/organizations/api_keys", json={"name": "x"})
        with pytest.raises(ReadOnlyViolation):
            client._client.delete("/v1/organizations/api_keys/apikey_x")
        client._client.get("/v1/organizations/users")

    assert reached == ["GET"]


def test_sync_clients_contain_no_direct_writing_http_calls() -> None:
    """The sync clients contain no direct write call; the shared request loop and OpenRouter's
    body-carrying analytics read remain the recorded exceptions."""
    package = Path(costura.__file__).parent / "providers"
    pattern = re.compile(r"\.(post|put|patch|delete|request)\(")
    # The two recorded exceptions, both behind GuardedTransport: the shared retry loop uses
    # `client.request` with the method its caller chose, and the OpenRouter analytics query is a
    # POST by API design.
    allowed = {"http.py": {"request"}, "openrouter/client.py": {"post"}}
    offenders = [
        f"{path.relative_to(package)}:{n}"
        for path in package.rglob("*.py")
        for n, line in enumerate(path.read_text().splitlines(), 1)
        for match in [pattern.search(line)]
        if match and match.group(1) not in allowed.get(str(path.relative_to(package)), set())
    ]
    assert offenders == []
