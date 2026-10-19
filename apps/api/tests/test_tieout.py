"""The redacted tie-out report: one row per provider and month with verdicts and percentages,
and nothing in the rendered text that names money, keys, workspaces or people."""

import json
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from costura.models import ProviderInvoice
from costura.ops import tieout as tieout_cli
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.inventory import run_inventory_sync
from costura.providers.anthropic.sync import run_cost_sync, run_usage_sync
from costura.spend.allocate import run_allocation
from costura.spend.ledger import costura_total
from costura.spend.tieout import FAIL, NONE, PASS, TieOutRow, render, tieout_report
from tests.conftest import ORG_ID, account_of, target
from tests.support.spend import AUGUST, FIXTURE_END, FIXTURE_START


def _synced(db_session: Session, client: AnthropicAdminClient) -> None:
    run_cost_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), client, FIXTURE_START, FIXTURE_END
    )
    run_usage_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), client, FIXTURE_START, FIXTURE_END
    )
    run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), client)
    run_allocation(db_session, ORG_ID, "anthropic", AUGUST)


def test_report_has_verdicts_and_percentages_but_no_identifiers(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client)
    total, _ = costura_total(db_session, ORG_ID, "anthropic", AUGUST)
    db_session.add(
        ProviderInvoice(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=account_of(db_session, ORG_ID, "anthropic"),
            month="2026-08",
            amount=(total * Decimal("1.10")).quantize(Decimal("0.01")),
        )
    )
    db_session.flush()

    rows = tieout_report(db_session, ORG_ID, months=3)
    assert [(row.provider, row.month) for row in rows] == [("anthropic", "2026-08")]
    row = rows[0]
    assert row.stored_rows in (PASS, NONE)
    assert row.attribution == PASS
    assert row.invoice_check == FAIL
    assert row.invoice_delta_percent is not None
    assert Decimal("-9.2") < row.invoice_delta_percent < Decimal("-9.0")
    assert row.provider_check in (PASS, FAIL, NONE)

    text = render(rows)
    assert text.splitlines()[0].startswith("provider")
    assert "anthropic" in text and "2026-08" in text
    for secret in ("@", "apikey_", "wrkspc_", str(total.quantize(Decimal("0.01")))):
        assert secret not in text


def test_cli_prints_the_table_and_refuses_an_unknown_org(
    db_session: Session,
    anthropic_client: AnthropicAdminClient,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _synced(db_session, anthropic_client)
    db_session.commit()
    monkeypatch.setattr(tieout_cli, "SessionLocal", lambda: _Borrowed(db_session))
    assert tieout_cli.main(["--org", "default", "--months", "1"]) == 0
    out = capsys.readouterr().out
    assert "anthropic  2026-08" in out
    assert tieout_cli.main(["--org", "default", "--months", "1", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["organization"] == "default"
    assert [(row["provider"], row["month"]) for row in body["rows"]] == [("anthropic", "2026-08")]
    assert tieout_cli.main(["--org", "nope"]) == 1
    assert tieout_cli.main(["--org", "nope", "--json"]) == 1
    with pytest.raises(SystemExit):
        tieout_cli.main(["--months", "0"])


def test_json_report_carries_verdicts_and_percentages_only() -> None:
    row = TieOutRow(
        provider="anthropic",
        month="2026-08",
        provider_check=PASS,
        provider_delta_percent=Decimal("0.0"),
        stored_rows=NONE,
        attribution=PASS,
        allocated_percent=Decimal("100.0"),
        invoice_check=FAIL,
        invoice_delta_percent=Decimal("-9.1"),
        people_percent=None,
    )
    text = tieout_cli.render_json([row], organization="default", months=3)
    body = json.loads(text)
    assert body == {
        "organization": "default",
        "months": 3,
        "rows": [
            {
                "provider": "anthropic",
                "month": "2026-08",
                "provider_check": "pass",
                "provider_delta_percent": 0.0,
                "stored_rows": "-",
                "attribution": "pass",
                "allocated_percent": 100.0,
                "invoice_check": "fail",
                "invoice_delta_percent": -9.1,
                "people_percent": None,
            }
        ],
    }
    assert set(body["rows"][0]) == {attribute for _, attribute in tieout_cli.COLUMNS}
    assert not any(key.endswith(("total", "amount")) for key in body["rows"][0])
    assert tieout_cli.render_json([], organization="empty", months=1) == (
        '{"organization": "empty", "months": 1, "rows": []}'
    )


class _Borrowed:
    """The test session as a context manager that does not close it."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, *_: object) -> None:
        return None
