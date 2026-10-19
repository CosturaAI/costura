from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import ProviderUser
from costura.providers.anthropic.inventory import api_keys_from_payload as anthropic_keys
from costura.providers.claude_ai.inventory import users_from_payload as claude_users
from costura.providers.copilot.inventory import users_from_payload as copilot_users
from costura.providers.cursor.client import CursorAdminClient
from costura.providers.cursor.inventory import run_inventory_sync as run_cursor_inventory
from costura.providers.cursor.sync import run_cost_total_sync as run_cursor_total
from costura.providers.openai.inventory import api_keys_from_payload as openai_keys
from costura.providers.openrouter.inventory import api_keys_from_payload as openrouter_keys
from tests.conftest import ORG_ID, load_fixture, target

CURSOR_START = datetime(2026, 9, 1, tzinfo=UTC)
CURSOR_END = datetime(2026, 9, 3, tzinfo=UTC)


def test_openai_keys_carry_their_last_use() -> None:
    payload = load_fixture("project_api_keys_proj_a.json", provider="openai")
    [key, *_] = openai_keys(payload, project_id="proj_a")
    assert key.last_used_at == datetime.fromtimestamp(1785600000, tz=UTC)
    assert key.limit_reported is False and key.spend_limit is None


def test_openrouter_keys_report_last_use_and_limit() -> None:
    base = load_fixture("keys_page1.json", provider="openrouter")["data"][0]
    unlimited, limited = openrouter_keys(
        {
            "data": [
                {**base, "last_used_at": "2026-10-13T08:00:00Z"},
                {
                    **base,
                    "hash": "b" * 64,
                    "limit": 50.5,
                    "limit_remaining": 12.25,
                    "limit_reset": "monthly",
                    "last_used_at": None,
                },
            ]
        }
    )
    assert unlimited.last_used_at == datetime(2026, 10, 13, 8, tzinfo=UTC)
    assert unlimited.limit_reported is True and unlimited.spend_limit is None
    assert limited.last_used_at is None
    assert (limited.spend_limit, limited.limit_remaining) == (Decimal("50.5"), Decimal("12.25"))
    assert limited.limit_reset == "monthly"


def test_anthropic_keys_read_both_principal_shapes_and_the_scope() -> None:
    base = {
        "type": "api_key",
        "name": "k",
        "created_at": "2026-01-20T10:00:00Z",
        "created_by": {"id": "user_a", "type": "user"},
        "partial_key_hint": None,
        "status": "active",
        "expires_at": None,
        "workspace_id": None,
    }
    current, service, legacy, unbound = anthropic_keys(
        {
            "data": [
                {
                    **base,
                    "id": "k1",
                    "principal": {"type": "user_actor", "user_id": "user_a"},
                    "scope": {"type": "organization"},
                },
                {
                    **base,
                    "id": "k2",
                    "principal": {"type": "service_account_actor", "service_account_id": "sa_1"},
                    "scope": {"type": "workspace", "workspace_id": "wrkspc_1"},
                },
                {**base, "id": "k3", "principal": {"id": "user_b", "type": "user"}},
                {**base, "id": "k4", "principal": None},
            ]
        }
    )
    assert (current.principal_external_id, current.principal_type) == ("user_a", "user")
    assert current.scope_type == "organization"
    assert (service.principal_external_id, service.principal_type) == ("sa_1", "service_account")
    assert service.scope_type == "workspace"
    assert (legacy.principal_external_id, legacy.principal_type) == ("user_b", "user")
    assert legacy.scope_type is None
    assert (unbound.principal_external_id, unbound.principal_type) == (None, None)


def test_cursor_spend_report_records_each_members_limit(
    db_session: Session, cursor_client: CursorAdminClient
) -> None:
    unit = target(db_session, ORG_ID, "cursor")
    run_cursor_inventory(db_session, unit, cursor_client)
    run_cursor_total(db_session, unit, cursor_client, CURSOR_START, CURSOR_END)

    users = {
        user.email: (user.limit_reported, user.spend_limit)
        for user in db_session.scalars(
            select(ProviderUser).where(ProviderUser.provider == "cursor")
        )
    }
    assert users["developer@example.com"] == (True, Decimal("500"))
    assert users["admin@example.com"] == (True, Decimal("100"))


def test_copilot_seats_and_claude_users_carry_their_last_activity() -> None:
    seats = load_fixture("seats_page1.json", provider="copilot")
    [seat, *_] = copilot_users(seats)
    assert seat.last_active_at == datetime(2026, 8, 2, 6, 53, 32, tzinfo=UTC)
    assert seat.pending_removal_at is None
    cancelled = copilot_users(
        {"seats": [{**seats["seats"][0], "pending_cancellation_date": "2026-10-31"}]}
    )
    assert cancelled[0].pending_removal_at == datetime(2026, 10, 31, tzinfo=UTC)

    [alpha, beta] = claude_users(load_fixture("users.json", provider="claude_ai"))
    assert alpha.last_active_at == datetime(2026, 9, 2, tzinfo=UTC)
    assert beta.last_active_at == datetime(2026, 9, 1, tzinfo=UTC)
