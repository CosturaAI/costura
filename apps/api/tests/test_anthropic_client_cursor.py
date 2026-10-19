import httpx
import pytest

from costura.providers.anthropic.client import AnthropicAdminClient, AnthropicApiError
from tests.conftest import anthropic_fixture_handler


def _client(handler) -> AnthropicAdminClient:
    return AnthropicAdminClient(
        admin_key="sk-ant-admin01-test",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )


def test_after_id_follows_last_id_until_has_more_false() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return anthropic_fixture_handler(request)

    with _client(handler) as client:
        pages = list(client.api_keys_pages())

    assert [p.page_index for p in pages] == [0, 1]
    assert [len(p.items) for p in pages] == [1, 2]
    first, second = (httpx.QueryParams(r.url.query) for r in seen)
    assert first["limit"] == "1000" and "after_id" not in first
    assert second["after_id"] == "apikey_redacted_1"
    assert pages[1].request_params["after_id"] == "apikey_redacted_1"


def test_workspaces_request_includes_archived() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert httpx.QueryParams(request.url.query)["include_archived"] == "true"
        return anthropic_fixture_handler(request)

    with _client(handler) as client:
        pages = list(client.workspaces_pages())

    assert [item["id"] for page in pages for item in page.items] == [
        "wrkspc_redacted_a",
        "wrkspc_redacted_archived",
    ]


def test_has_more_without_last_id_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "has_more": True})

    with _client(handler) as client, pytest.raises(AnthropicApiError, match="no last_id"):
        list(client.users_pages())


def test_members_of_unknown_workspace_raise_with_status() -> None:
    with _client(anthropic_fixture_handler) as client:
        members = list(client.workspace_members_pages("wrkspc_redacted_a"))
        assert [m["user_id"] for m in members[0].items] == [
            "user_redacted_alice",
            "user_redacted_bob",
        ]
        with pytest.raises(AnthropicApiError) as excinfo:
            list(client.workspace_members_pages("wrkspc_redacted_archived"))

    assert excinfo.value.status_code == 404
