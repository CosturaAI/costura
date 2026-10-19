"""Cursor client authentication, allowlist, inclusive windows, and pagination."""

import base64
import json
from datetime import UTC, datetime

import httpx
import pytest

from costura.providers.cursor.client import (
    MAX_PAGE_SIZE,
    CursorAdminClient,
    CursorAuthError,
    allow_cursor,
)
from costura.providers.http import ReadOnlyViolation
from tests.conftest import cursor_fixture_handler

START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 8, 3, tzinfo=UTC)


def _client(handler=cursor_fixture_handler) -> CursorAdminClient:
    return CursorAdminClient(
        api_key="key_test",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )


def test_members_use_basic_auth_with_key_as_username() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return cursor_fixture_handler(request)

    with _client(handler) as client:
        page = next(client.members_pages())

    assert len(page.items) == 3
    expected = base64.b64encode(b"key_test:").decode()
    assert requests[0].headers["authorization"] == f"Basic {expected}"


def test_usage_pages_use_inclusive_millisecond_bounds_and_page_limit() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return cursor_fixture_handler(request)

    with _client(handler) as client:
        pages = list(client.filtered_usage_events_pages(START, END))

    assert [page.page_index for page in pages] == [0, 1]
    assert [len(page.results) for page in pages] == [3, 2]
    assert bodies[0] == {
        "startDate": 1785542400000,
        "endDate": 1785715199999,
        "page": 1,
        "pageSize": MAX_PAGE_SIZE,
    }
    assert bodies[1]["page"] == 2


@pytest.mark.parametrize("page_size", [0, MAX_PAGE_SIZE + 1])
def test_usage_page_size_is_bounded(page_size: int) -> None:
    with _client() as client, pytest.raises(ValueError, match="page_size"):
        list(client.filtered_usage_events_pages(START, END, page_size=page_size))


def test_allowlist_rejects_every_other_cursor_write() -> None:
    base = "https://api.cursor.com"
    assert allow_cursor(httpx.Request("GET", f"{base}/teams/members"))
    assert allow_cursor(httpx.Request("POST", f"{base}/teams/filtered-usage-events"))
    assert allow_cursor(httpx.Request("POST", f"{base}/teams/spend"))
    assert allow_cursor(httpx.Request("POST", f"{base}/teams/daily-usage-data"))
    assert not allow_cursor(httpx.Request("POST", f"{base}/teams/user-spend-limit"))
    assert not allow_cursor(httpx.Request("GET", f"{base}/teams/filtered-usage-events"))

    with _client() as client, pytest.raises(ReadOnlyViolation):
        client._client.post("/teams/remove-member")


def test_daily_usage_splits_windows_at_30_days_and_keeps_raw_pages() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json={"data": [{"day": "2026-08-01"}]})

    with _client(handler) as client:
        pages = list(
            client.daily_usage_pages(
                datetime(2026, 8, 1, tzinfo=UTC),
                datetime(2026, 9, 15, tzinfo=UTC),
            )
        )

    assert len(pages) == 2
    assert bodies[0]["endDate"] - bodies[0]["startDate"] == 30 * 86_400_000 - 1
    assert pages[0].payload == {"data": [{"day": "2026-08-01"}]}


def test_spend_control_field_follows_included_setting() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"teamMemberSpend": [], "subscriptionCycleStart": 1785542400000},
        )

    with _client(handler) as client:
        [included] = list(client.spend_pages(include_included_in_business=True))
        [excluded] = list(client.spend_pages(include_included_in_business=False))

    assert [request.url.path for request in requests] == ["/teams/spend", "/teams/spend"]
    assert included.request_params["_costura_control_field"] == "overallSpendCents"
    assert excluded.request_params["_costura_control_field"] == "spendCents"


def test_spend_pages_follow_total_pages() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(
            200,
            json={
                "teamMemberSpend": [{"email": f"member-{body['page']}@example.com"}],
                "subscriptionCycleStart": 1785542400000,
                "totalPages": 2,
            },
        )

    with _client(handler) as client:
        pages = list(client.spend_pages(include_included_in_business=True))

    assert [body["page"] for body in bodies] == [1, 2]
    assert [page.page_index for page in pages] == [0, 1]


def test_auth_errors_are_typed() -> None:
    def forbidden(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "invalid API key"})

    with _client(forbidden) as client, pytest.raises(CursorAuthError) as info:
        next(client.members_pages())
    assert info.value.status_code == 403
