"""Canonical names and lifecycle metadata for AI models and token types."""

import re
from dataclasses import dataclass
from datetime import date

CATALOG_SNAPSHOT_DATE = date(2026, 10, 10)

MODEL_BRAND = "model_brand"
MODEL_FAMILY = "model_family"
MODEL_NAME = "model_name"
MODEL_CHANNEL = "model_channel"
MODEL_LIFECYCLE = "model_lifecycle"
TOKEN_TYPE = "token_type"
MODEL_DIMENSIONS = (
    MODEL_BRAND,
    MODEL_FAMILY,
    MODEL_NAME,
    MODEL_CHANNEL,
    MODEL_LIFECYCLE,
)
TAXONOMY_DIMENSIONS = (*MODEL_DIMENSIONS, TOKEN_TYPE)


@dataclass(frozen=True)
class CatalogEntry:
    brand: str
    family: str
    name: str
    pattern: str
    lifecycle: str = "Current"
    deprecated_on: date | None = None
    retired_on: date | None = None
    tier: int | None = None


@dataclass(frozen=True)
class CanonicalModel:
    brand: str
    family: str
    name: str
    channel: str
    lifecycle: str
    raw_model: str
    tier: int | None = None

    def value(self, dimension: str) -> str:
        values = {
            MODEL_BRAND: self.brand,
            MODEL_FAMILY: self.family,
            MODEL_NAME: self.name,
            MODEL_CHANNEL: self.channel,
            MODEL_LIFECYCLE: self.lifecycle,
        }
        return values[dimension]


CATALOG = (
    # Deprecation and retirement dates: Anthropic's model deprecations page, read on the
    # snapshot date. `deprecated_on` reads as Legacy, `retired_on` as Deprecated.
    CatalogEntry(
        "Claude",
        "Claude Haiku",
        "Claude 3.5 Haiku",
        r"claude-(?:3-5-haiku|haiku-3-5)",
        deprecated_on=date(2025, 12, 19),
        retired_on=date(2026, 2, 19),
        tier=1,
    ),
    CatalogEntry("Claude", "Claude Haiku", "Claude 4.5 Haiku", r"claude-haiku-4[.-]5", tier=1),
    CatalogEntry(
        "Claude",
        "Claude Sonnet",
        "Claude 4 Sonnet",
        r"claude-sonnet-4",
        deprecated_on=date(2026, 4, 14),
        retired_on=date(2026, 6, 15),
        tier=2,
    ),
    CatalogEntry(
        "Claude",
        "Claude Sonnet",
        "Claude 4.5 Sonnet",
        r"claude-sonnet-4[.-]5",
        deprecated_on=date(2026, 9, 30),
        retired_on=date(2026, 11, 30),
        tier=2,
    ),
    CatalogEntry("Claude", "Claude Sonnet", "Claude 4.6 Sonnet", r"claude-sonnet-4[.-]6", tier=2),
    CatalogEntry(
        "Claude",
        "Claude Opus",
        "Claude 4.1 Opus",
        r"claude-opus-4-1",
        deprecated_on=date(2026, 6, 5),
        retired_on=date(2026, 8, 5),
        tier=3,
    ),
    CatalogEntry("Claude", "Claude Opus", "Claude Opus 5", r"claude-opus-5", tier=3),
    CatalogEntry("GPT", "GPT-4o", "GPT-4o", r"gpt-4o", tier=2),
    CatalogEntry("GPT", "GPT-4o", "GPT-4o mini", r"gpt-4o-mini", tier=1),
    CatalogEntry("GPT", "GPT-5", "GPT-5.2", r"gpt-5[.-]2", tier=3),
    CatalogEntry("GPT", "GPT Image", "GPT Image 1", r"gpt-image-1"),
    CatalogEntry(
        "OpenAI",
        "OpenAI Embeddings",
        "Text Embedding 3 Large",
        r"text-embedding-3-large",
    ),
    CatalogEntry(
        "OpenAI",
        "OpenAI Moderation",
        "Omni Moderation",
        r"omni-moderation-latest",
    ),
    CatalogEntry("OpenAI", "OpenAI Audio", "TTS 1", r"tts-1"),
    CatalogEntry("OpenAI", "Whisper", "Whisper 1", r"whisper-1"),
    CatalogEntry("Grok", "Grok 4", "Grok 4.6", r"grok-4[.-]6"),
)

_COMPILED_CATALOG = tuple(
    (re.compile(rf"^{entry.pattern}$", re.IGNORECASE), entry) for entry in CATALOG
)
_DATE_SUFFIX = re.compile(r"-(?:20\d{2})-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$|-(?:20\d{6})$")

TOKEN_TYPE_LABELS = {
    "uncached_input_tokens": "Input",
    "input_tokens": "Input",
    "input": "Input",
    "output_tokens": "Output",
    "output": "Output",
    "cache_read_tokens": "Cache Read",
    "cache_read_input_tokens": "Cache Read",
    "cached_input_tokens": "Cache Read",
    "cache_creation_5m_tokens": "Cache Write",
    "cache_creation_1h_tokens": "Cache Write",
    "cache_creation.ephemeral_5m_input_tokens": "Cache Write",
    "cache_creation.ephemeral_1h_input_tokens": "Cache Write",
    "reasoning_tokens": "Reasoning",
}


def lifecycle_on(entry: CatalogEntry, day: date) -> str:
    if entry.retired_on is not None and day >= entry.retired_on:
        return "Deprecated"
    if entry.deprecated_on is not None and day >= entry.deprecated_on:
        return "Legacy"
    return entry.lifecycle


def catalog_entry(model: str | None) -> CatalogEntry | None:
    normalized = _normalized_model(model)
    for pattern, entry in _COMPILED_CATALOG:
        if pattern.fullmatch(normalized):
            return entry
    return None


def resolve(
    provider: str,
    model: str | None,
    *,
    day: date | None = None,
) -> CanonicalModel:
    raw_model = (model or "(none)").strip() or "(none)"
    entry = catalog_entry(raw_model)
    channel = model_channel(provider, raw_model)
    if entry is None:
        return CanonicalModel("Other", "Other", raw_model, channel, "Unknown", raw_model)
    return CanonicalModel(
        entry.brand,
        entry.family,
        entry.name,
        channel,
        lifecycle_on(entry, day or CATALOG_SNAPSHOT_DATE),
        raw_model,
        entry.tier,
    )


CHANNEL_LABELS = {
    "anthropic": "Anthropic API",
    "claude_ai": "Claude.ai",
    "openai": "OpenAI API",
    "aws.bedrock": "Amazon Bedrock",
    "bedrock": "Amazon Bedrock",
    "gcp.vertex_ai": "Vertex AI",
    "vertex_ai": "Vertex AI",
    "vertex": "Vertex AI",
    "azure.ai": "Azure AI Foundry",
    "azure_openai": "Azure AI Foundry",
    "azure": "Azure AI Foundry",
}
ROUTER_LABELS = {"openrouter": "OpenRouter"}
UPSTREAM_LABELS = {"anthropic": "Anthropic", "openai": "OpenAI", "x-ai": "xAI"}


def model_channel(provider: str, model: str | None = None) -> str:
    """Where a model was bought: a vendor API, a router (named with the upstream vendor from
    the model id), a cloud platform, or the OpenTelemetry source that reported it."""
    normalized = provider.casefold().strip()
    if normalized in CHANNEL_LABELS:
        return CHANNEL_LABELS[normalized]
    if normalized in ROUTER_LABELS:
        upstream = (model or "").partition("/")[0]
        vendor = UPSTREAM_LABELS.get(upstream.casefold(), upstream or "Unknown")
        return f"{ROUTER_LABELS[normalized]} ({vendor})"
    return f"OpenTelemetry ({provider})" if provider else "Unknown"


def token_type_label(value: str | None) -> str:
    if not value:
        return "Other"
    return TOKEN_TYPE_LABELS.get(value.casefold(), "Other")


def _normalized_model(model: str | None) -> str:
    value = (model or "").strip()
    if "/" in value:
        value = value.partition("/")[2]
    return _DATE_SUFFIX.sub("", value)


__all__ = [
    "CATALOG",
    "CATALOG_SNAPSHOT_DATE",
    "MODEL_DIMENSIONS",
    "TAXONOMY_DIMENSIONS",
    "CanonicalModel",
    "CatalogEntry",
    "catalog_entry",
    "lifecycle_on",
    "model_channel",
    "resolve",
    "token_type_label",
]
