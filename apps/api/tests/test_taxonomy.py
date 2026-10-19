import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from costura.demo.manifest import ACCOUNTS, Account
from costura.spend.taxonomy import (
    CATALOG,
    CATALOG_SNAPSHOT_DATE,
    CatalogEntry,
    lifecycle_on,
    resolve,
    token_type_label,
)
from tests.seed import RATES

FIXTURES = Path(__file__).parent / "fixtures"


def models(account: Account) -> set[str]:
    found = {stream.model for stream in account.streams}
    found.update(stream.switch[1] for stream in account.streams if stream.switch is not None)
    return found


UNKNOWN_MODELS = frozenset({"mistralai/devstral-medium", "gpt-4.1-nano-2025-04-14", "composer-2"})


def _models(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = {value["model"]} if isinstance(value.get("model"), str) else set()
        return found | set().union(*(_models(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_models(item) for item in value), set())
    return set()


def test_catalog_resolves_every_fixture_demo_and_seed_model() -> None:
    names = set(RATES)
    for directory in ("anthropic", "openai", "openrouter"):
        for path in (FIXTURES / directory).glob("*.json"):
            names.update(_models(json.loads(path.read_text())))
    pairs = {("openrouter" if "/" in model else "anthropic", model) for model in names}
    pairs.update(
        (account.provider, model)
        for account in ACCOUNTS
        for model in models(account)
        if model not in UNKNOWN_MODELS
    )

    assert pairs
    assert {pair for pair in pairs if resolve(*pair).brand == "Other"} == set()
    assert {
        model for account in ACCOUNTS for model in models(account) if model in UNKNOWN_MODELS
    } == UNKNOWN_MODELS
    assert all(resolve("openai", model).lifecycle == "Unknown" for model in UNKNOWN_MODELS)


@pytest.mark.skipif(
    os.environ.get("COSTURA_CHECK_CATALOG_FRESHNESS") != "1",
    reason="calendar check; the weekly Images workflow runs it",
)
def test_catalog_snapshot_is_not_older_than_ninety_days() -> None:
    assert date.today() - CATALOG_SNAPSHOT_DATE <= timedelta(days=90)


def test_resolve_normalizes_names_and_channels() -> None:
    mini = resolve("openai", "gpt-4o-mini-2024-07-18")
    assert (mini.name, mini.tier) == ("GPT-4o mini", 1)
    sonnet = resolve("anthropic", "claude-sonnet-4-6")
    assert (sonnet.family, sonnet.tier) == ("Claude Sonnet", 2)
    assert resolve("anthropic", "claude-opus-5").tier == 3
    openrouter = resolve("openrouter", "anthropic/claude-sonnet-4.6")
    assert openrouter.name == "Claude 4.6 Sonnet"
    assert openrouter.channel == "OpenRouter (Anthropic)"
    unknown = resolve("otel.vendor", "private-model")
    assert (unknown.brand, unknown.family, unknown.name, unknown.lifecycle) == (
        "Other",
        "Other",
        "private-model",
        "Unknown",
    )


def test_lifecycle_is_evaluated_for_the_line_day() -> None:
    entry = CatalogEntry(
        "GPT",
        "GPT-4",
        "GPT-4",
        "gpt-4",
        deprecated_on=date(2026, 6, 1),
        retired_on=date(2026, 9, 1),
    )
    assert lifecycle_on(entry, date(2026, 5, 31)) == "Current"
    assert lifecycle_on(entry, date(2026, 6, 1)) == "Legacy"
    assert lifecycle_on(entry, date(2026, 9, 1)) == "Deprecated"
    assert all(entry.pattern for entry in CATALOG)


def test_token_type_labels_use_one_provider_neutral_vocabulary() -> None:
    assert token_type_label("uncached_input_tokens") == "Input"
    assert token_type_label("cache_creation.ephemeral_5m_input_tokens") == "Cache Write"
    assert token_type_label("reasoning_tokens") == "Reasoning"
    assert token_type_label("provider_specific") == "Other"
