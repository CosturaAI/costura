"""Provider ids that become one path segment of a provider URL."""

import httpx
import pytest

from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.http import path_segment


@pytest.mark.parametrize(
    ("value", "segment"),
    [
        ("wrkspc_01", "wrkspc_01"),
        ("a/b", "a%2Fb"),
        ("x?admin=1", "x%3Fadmin%3D1"),
        ("x#frag", "x%23frag"),
        ("../keys", "..%2Fkeys"),
    ],
)
def test_ids_are_quoted_into_one_segment(value: str, segment: str) -> None:
    assert path_segment(value) == segment


@pytest.mark.parametrize("value", ["", ".", ".."])
def test_dot_segments_are_refused(value: str) -> None:
    with pytest.raises(ValueError):
        path_segment(value)


def test_a_workspace_id_cannot_leave_its_members_path() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"data": [], "has_more": False})

    client = AnthropicAdminClient(
        admin_key="sk-ant-admin01-test", transport=httpx.MockTransport(handler)
    )
    list(client.workspace_members_pages("ws?limit=1#x"))
    assert seen[0].startswith("/v1/organizations/workspaces/ws%3Flimit%3D1%23x/members")
