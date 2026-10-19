import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import ProviderInventoryEvent
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.inventory import run_inventory_sync
from tests.conftest import ORG_ID, anthropic_fixture_handler, load_fixture, target


def _client(keys: list[dict]) -> AnthropicAdminClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api_keys"):
            return httpx.Response(200, json={"data": keys, "has_more": False, "last_id": None})
        return anthropic_fixture_handler(request)

    return AnthropicAdminClient(
        admin_key="k", transport=httpx.MockTransport(handler), max_retries=0, sleep=lambda _: None
    )


def _events(session: Session) -> set[tuple[str, str, str | None, str | None]]:
    return {
        (row.external_id, row.event, row.from_status, row.to_status)
        for row in session.scalars(
            select(ProviderInventoryEvent).where(ProviderInventoryEvent.entity_kind == "api_key")
        )
    }


def test_a_second_listing_records_what_changed_and_the_first_records_nothing(
    db_session: Session,
) -> None:
    first, second, third = (
        load_fixture("api_keys_page1.json")["data"] + load_fixture("api_keys_page2.json")["data"]
    )
    unit = target(db_session, ORG_ID, "anthropic")
    with _client([first, second, third]) as client:
        run_inventory_sync(db_session, unit, client)
    assert _events(db_session) == set()

    new = {**first, "id": "apikey_new", "name": "new-key"}
    with _client([{**first, "status": "inactive"}, third, new]) as client:
        run_inventory_sync(db_session, unit, client)
    assert _events(db_session) == {
        (first["id"], "status_changed", "active", "inactive"),
        (second["id"], "missing", second["status"], second["status"]),
        ("apikey_new", "created", None, "active"),
    }

    with _client([{**first, "status": "inactive"}, second, third, new]) as client:
        run_inventory_sync(db_session, unit, client)
    assert (second["id"], "returned", second["status"], second["status"]) in _events(db_session)
