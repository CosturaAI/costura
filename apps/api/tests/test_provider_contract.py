"""Conformance every connector owes: the spec is complete, money reaches storage through
`to_storage`, and a second sync of the same window is idempotent.

The checks that need a live client run against the fixture transports in `conftest`.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import credit_prices
from costura.models import ProviderSyncRun, SpendCostLine
from costura.providers.registry import PROVIDERS
from costura.providers.spec import ProviderSpec
from costura.spend.money import STORAGE_EXPONENT
from tests.conftest import ORG_ID, target
from tests.test_codex_sync import WORKSPACE_ID, CodexFixtureClient

START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 8, 5, tzinfo=UTC)
SEPTEMBER = (datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
CODEX_DAY = (datetime(2026, 9, 18, tzinfo=UTC), datetime(2026, 9, 19, tzinfo=UTC))

# Providers whose fixture client the suite can build: the client fixture name and the
# window its recorded pages cover.
FIXTURED = {
    "anthropic": ("anthropic_client", (START, END)),
    "openai": ("openai_client", (START, END)),
    "openrouter": ("openrouter_client", (START, END)),
    "cursor": ("cursor_client", (START, END)),
    "copilot": ("copilot_client", (START, END)),
    "claude_ai": ("claude_ai_client", SEPTEMBER),
    "codex": ("codex_client", CODEX_DAY),
}


@pytest.fixture
def codex_client(db_session: Session) -> CodexFixtureClient:
    unit = target(db_session, ORG_ID, "codex")
    credit_prices.codex_account(db_session, ORG_ID, unit.account_id).external_id = WORKSPACE_ID
    credit_prices.create_price(
        db_session,
        ORG_ID,
        unit.account_id,
        effective_from=date(2026, 9, 18),
        price_per_credit=Decimal("0.08"),
        created_by=None,
        today=date(2026, 9, 18),
    )
    return CodexFixtureClient()


@pytest.mark.parametrize("spec", PROVIDERS.values(), ids=PROVIDERS.keys())
def test_spec_names_its_contract(spec: ProviderSpec) -> None:
    """Every spec declares the pieces the scheduler and reconcile read."""
    step_names = [name for name, _ in spec.sync_steps]
    assert spec.cost_endpoint
    assert spec.allocation_inputs
    assert set(spec.allocation_inputs) <= set(step_names)
    assert spec.auth_error and spec.api_error
    assert issubclass(spec.auth_error, spec.api_error)


def test_every_provider_has_a_fixture_client() -> None:
    """A new connector joins the idempotency check below, not only the spec check."""
    assert set(FIXTURED) == set(PROVIDERS)


@pytest.mark.parametrize("provider", sorted(FIXTURED))
def test_second_sync_is_idempotent(
    request: pytest.FixtureRequest, db_session: Session, provider: str
) -> None:
    """Running the cost step twice over the same window writes the same rows once."""
    spec = PROVIDERS[provider]
    fixture_name, (start, end) = FIXTURED[provider]
    client = request.getfixturevalue(fixture_name)
    cost_step = dict(spec.sync_steps)["cost"]
    scope = target(db_session, ORG_ID, provider)

    def stored() -> list[Decimal]:
        return sorted(
            db_session.scalars(
                select(SpendCostLine.amount).where(SpendCostLine.provider == provider)
            ).all()
        )

    cost_step(db_session, scope, client, start, end)
    first = stored()
    cost_step(db_session, scope, client, start, end)
    amounts = stored()

    assert amounts == first
    assert amounts
    assert all(amount == amount.quantize(STORAGE_EXPONENT) for amount in amounts)


def test_runs_record_utc_datetimes(db_session: Session, anthropic_client: object) -> None:
    """A sync run stores timezone-aware UTC bounds."""
    spec = PROVIDERS["anthropic"]
    cost_step = dict(spec.sync_steps)["cost"]
    cost_step(db_session, target(db_session, ORG_ID, "anthropic"), anthropic_client, START, END)
    run = db_session.scalars(select(ProviderSyncRun).order_by(ProviderSyncRun.id.desc())).first()
    assert run is not None
    assert run.window_start is not None and run.window_start.tzinfo is not None
    assert run.window_end is not None and run.window_end.tzinfo is not None
