"""OpenAI Admin client: GET-only guard, report and listing pagination, auth and rate limits."""

from datetime import UTC, datetime

import httpx
import pytest

from costura.providers.http import ReadOnlyViolation
from costura.providers.openai.client import (
    COST_BY_KEY_GROUP_BY,
    COST_GROUP_BY,
    USAGE_FAMILY_GROUP_BY,
    USAGE_GROUP_BY,
    OpenAIAdminClient,
    OpenAIApiError,
    OpenAIAuthError,
    unix_seconds,
)
from tests.conftest import openai_fixture_handler

NO_SLEEP = lambda _: None  # noqa: E731
START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 9, 1, tzinfo=UTC)


def _client(handler, **kwargs) -> OpenAIAdminClient:
    return OpenAIAdminClient(
        admin_key="sk-admin-test",
        transport=httpx.MockTransport(handler),
        sleep=NO_SLEEP,
        **kwargs,
    )


def test_every_write_verb_is_refused_before_network_io() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        return httpx.Response(200, json={"data": []})

    with _client(handler) as client:
        for method, path in (
            ("POST", "/organization/projects"),
            ("POST", "/organization/projects/proj_a/api_keys"),
            ("DELETE", "/organization/projects/proj_a/api_keys/key_a1"),
            ("POST", "/organization/invites"),
            ("PATCH", "/organization/users/user_x"),
        ):
            with pytest.raises(ReadOnlyViolation, match="read-only"):
                client._client.request(method, path)
        list(client.projects_pages())
    assert calls == ["GET /v1/organization/projects"]


def test_report_pages_send_unix_window_group_by_and_follow_next_page() -> None:
    queries: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries.append(httpx.QueryParams(request.url.query))
        return openai_fixture_handler(request)

    with _client(handler) as client:
        pages = list(client.costs_pages(START, END))
        totals = list(client.costs_total_pages(START, END))
        by_key = list(client.costs_by_key_pages(START, END))
        usage = list(client.usage_completions_pages(START, END))

    assert [p.page_index for p in pages] == [0, 1]
    assert pages[0].next_page == "page_costs_2" and pages[1].next_page is None
    assert len(pages[0].results) == 9 and len(pages[1].results) == 5
    first, second = queries[0], queries[1]
    assert first.get("start_time") == str(unix_seconds(START))
    assert first.get("end_time") == str(unix_seconds(END))
    assert first.get("bucket_width") == "1d" and first.get("limit") == "180"
    assert tuple(first.get_list("group_by")) == COST_GROUP_BY
    assert first.get("page") is None and second.get("page") == "page_costs_2"
    assert pages[1].request_params["page"] == "page_costs_2"
    assert pages[1].request_params["group_by"] == list(COST_GROUP_BY)

    assert len(totals) == 1 and queries[2].get_list("group_by") == []
    assert len(by_key) == 1 and tuple(queries[3].get_list("group_by")) == COST_BY_KEY_GROUP_BY
    assert [p.page_index for p in usage] == [0, 1]
    assert tuple(queries[4].get_list("group_by")) == USAGE_GROUP_BY
    assert queries[4].get("limit") == "31"


def test_report_pages_reject_an_empty_window_and_naive_timestamps() -> None:
    with _client(openai_fixture_handler) as client:
        with pytest.raises(ValueError, match="before"):
            list(client.costs_pages(END, START))
        with pytest.raises(ValueError, match="timezone-aware"):
            list(client.costs_pages(START.replace(tzinfo=None), END.replace(tzinfo=None)))


@pytest.mark.parametrize(("family", "group_by"), USAGE_FAMILY_GROUP_BY.items())
def test_activity_family_uses_its_supported_grouping(
    family: str, group_by: tuple[str, ...]
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return openai_fixture_handler(request)

    with _client(handler) as client:
        pages = list(client.usage_family_pages(family, START, END))

    assert len(pages) == 1
    assert seen[0].url.path == f"/v1/organization/usage/{family}"
    params = httpx.QueryParams(seen[0].url.query)
    assert tuple(params.get_list("group_by")) == group_by
    assert params.get("bucket_width") == "1d"
    assert params.get("limit") == "31"


def test_activity_family_rejects_an_unknown_endpoint() -> None:
    with (
        _client(openai_fixture_handler) as client,
        pytest.raises(ValueError, match="unknown OpenAI usage family"),
    ):
        list(client.usage_family_pages("unknown", START, END))


def test_listing_pages_follow_after_until_has_more_is_false() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = httpx.QueryParams(request.url.query)
        seen.append(params.get("after"))
        assert params.get("limit") == "100"
        assert params.get("include_archived") == "true"
        if params.get("after") is None:
            items = [{"id": f"proj_{i}"} for i in range(100)]
            return httpx.Response(200, json={"data": items, "has_more": True, "last_id": "proj_99"})
        return httpx.Response(200, json={"data": [{"id": "proj_100"}], "has_more": False})

    with _client(handler) as client:
        pages = list(client.projects_pages())

    assert seen == [None, "proj_99"]
    assert [len(p.items) for p in pages] == [100, 1]
    assert pages[1].request_params == {
        "include_archived": "true",
        "limit": "100",
        "after": "proj_99",
    }


def test_project_listings_carry_the_project_in_the_path() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path + "?" + request.url.query.decode())
        return openai_fixture_handler(request)

    with _client(handler) as client:
        keys = list(client.project_api_keys_pages("proj_a"))
        users = list(client.project_users_pages("proj_b"))

    assert [k["id"] for k in keys[0].items] == ["key_a1", "key_a2"]
    assert [u["id"] for u in users[0].items] == ["user_x"]
    assert paths[0].startswith("/v1/organization/projects/proj_a/api_keys?")
    assert "owner_project_access=any" in paths[0]
    assert paths[1].startswith("/v1/organization/projects/proj_b/users?")


def test_auth_errors_carry_the_status_and_hide_the_body() -> None:
    def forbidden(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"message": "Incorrect API key provided: sk-admin-secret"}}
        )

    with _client(forbidden) as client, pytest.raises(OpenAIAuthError) as info:
        list(client.projects_pages())
    assert info.value.status_code == 401
    assert "secret" not in info.value.public and "/organization/projects" in info.value.public
    assert isinstance(info.value, OpenAIApiError)


def test_retries_on_429_and_honours_retry_after() -> None:
    attempts: list[int] = []
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(429, headers={"retry-after": "2"})
        return openai_fixture_handler(request)

    client = OpenAIAdminClient(
        admin_key="k", transport=httpx.MockTransport(handler), sleep=slept.append
    )
    with client:
        assert len(next(iter(client.users_pages())).items) == 2
    assert len(attempts) == 3
    assert slept == [2.0, 2.0]


def test_exhausted_429_is_marked_temporarily_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    with _client(handler, max_retries=0) as client, pytest.raises(OpenAIApiError) as info:
        list(client.users_pages())

    assert info.value.status_code == 429
    assert info.value.unavailable is True
