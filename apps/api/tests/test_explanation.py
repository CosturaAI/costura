from datetime import date
from decimal import Decimal

from costura.spend.decomposition import Decomposition
from costura.spend.explanation import Driver, explain

KEY = Driver(kind="api_key", label="ci-agents", share=Decimal("0.71"))
MODEL = Driver(kind="model", label="claude-opus-4-1", share=Decimal("0.9"))


def test_a_spike_names_its_main_principal_share_and_model() -> None:
    sentence = explain(
        kind="spike",
        label="organization total",
        impact=Decimal("380"),
        impact_percent=Decimal("38"),
        actual=Decimal("1380"),
        impact_share=None,
        drivers=[KEY, MODEL],
    )
    assert sentence == (
        "organization total spent 380.00 USD more than expected (38% over); "
        "ci-agents accounts for 71% of the increase, on claude-opus-4-1."
    )


def test_a_drop_reads_as_less_and_under() -> None:
    sentence = explain(
        kind="drop",
        label="gateway",
        impact=Decimal("97.88"),
        impact_percent=Decimal("55.52"),
        actual=Decimal("27.22"),
        impact_share=None,
        drivers=[Driver(kind="api_key", label="or_gateway", share=Decimal("1"))],
    )
    assert sentence == (
        "gateway spent 97.88 USD less than expected (56% under); "
        "or_gateway accounts for 100% of the drop."
    )


def test_a_new_principal_states_its_first_day() -> None:
    sentence = explain(
        kind="new_principal",
        label="key_new",
        impact=Decimal("420"),
        impact_percent=None,
        actual=Decimal("420"),
        impact_share=Decimal("0.123"),
        drivers=[],
    )
    assert (
        sentence == "key_new is new: 420.00 USD on its first day, 12% of the month's spend to date."
    )


def test_the_detail_adds_the_model_switch_and_its_day() -> None:
    split = Decomposition(
        change=Decimal("380"),
        volume=Decimal("40"),
        mix=Decimal("340"),
        price=Decimal("0"),
        top_model="claude-opus-4-1",
        top_share_baseline=Decimal("0.1"),
        top_share_day=Decimal("0.8"),
        switch_day=date(2026, 10, 13),
    )
    sentence = explain(
        kind="spike",
        label="ci-agents",
        impact=Decimal("380"),
        impact_percent=Decimal("38"),
        actual=Decimal("1380"),
        impact_share=None,
        drivers=[MODEL],
        split=split,
    )
    assert sentence.endswith("; claude-opus-4-1 rose to 80% of tokens from 10% on 2026-10-13.")
    assert "claude-opus-4-1 accounts for 90% of the increase" in sentence
