"""One day of one sample account as the provider's own API would report it: the result rows of
the cost, usage, total and activity reports, built from the manifest streams.

Money is derived from tokens at each model's list price, so the cost report, the usage report
and the control total of a day agree to the digit, the way a provider's own reports do. The
normalizers in `costura.providers` read these rows exactly as they read live responses."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any

from costura.demo.manifest import (
    CURSOR_INCLUDED_USD,
    Account,
    Activity,
    Stream,
)
from costura.demo.values import cents, growth, micro, noise, unit, weekday_factor

MILLION = Decimal("1000000")
WEB_SEARCH_PRICE = Decimal("0.01")

# USD per million tokens: input, output, 5-minute cache write, 1-hour cache write, cache read.
ANTHROPIC_PRICES: dict[str, tuple[Decimal, Decimal, Decimal, Decimal, Decimal]] = {
    "claude-opus-4-1": (
        Decimal("15"),
        Decimal("75"),
        Decimal("18.75"),
        Decimal("30"),
        Decimal("1.5"),
    ),
    "claude-sonnet-4": (Decimal("3"), Decimal("15"), Decimal("3.75"), Decimal("6"), Decimal("0.3")),
    "claude-sonnet-4-5": (
        Decimal("3"),
        Decimal("15"),
        Decimal("3.75"),
        Decimal("6"),
        Decimal("0.3"),
    ),
    "claude-haiku-3-5": (
        Decimal("0.8"),
        Decimal("4"),
        Decimal("1"),
        Decimal("1.6"),
        Decimal("0.08"),
    ),
    "claude-opus-5": (Decimal("5"), Decimal("25"), Decimal("6.25"), Decimal("10"), Decimal("0.5")),
    "claude-haiku-4-5": (Decimal("1"), Decimal("5"), Decimal("1.25"), Decimal("2"), Decimal("0.1")),
}
ANTHROPIC_LABELS = {
    "claude-opus-4-1": "Claude Opus 4.1",
    "claude-sonnet-4": "Claude Sonnet 4",
    "claude-sonnet-4-5": "Claude Sonnet 4.5",
    "claude-haiku-3-5": "Claude Haiku 3.5",
    "claude-opus-5": "Claude Opus 5",
    "claude-haiku-4-5": "Claude Haiku 4.5",
}
# Cost report token type, its share of a stream's money, and the label in the description.
ANTHROPIC_TOKEN_TYPES = (
    ("uncached_input_tokens", Decimal("0.22"), "Input Tokens"),
    ("output_tokens", Decimal("0.48"), "Output Tokens"),
    ("cache_read_input_tokens", Decimal("0.12"), "Cache Read"),
    ("cache_creation.ephemeral_5m_input_tokens", Decimal("0.18"), "Cache Write (5m)"),
)
# A stream that caches for an hour moves part of its write share to the 1-hour cache.
ANTHROPIC_1H_SHARE = Decimal("0.08")
BATCH_DISCOUNT = Decimal("0.5")
LONG_CONTEXT = "200k-1M"

# USD per million: input, cached input, output.
OPENAI_PRICES: dict[str, tuple[Decimal, Decimal, Decimal]] = {
    "gpt-5.2": (Decimal("1.75"), Decimal("0.175"), Decimal("14")),
    "gpt-4o": (Decimal("2.5"), Decimal("1.25"), Decimal("10")),
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.075"), Decimal("0.6")),
    "gpt-4.1-nano-2025-04-14": (Decimal("0.1"), Decimal("0.025"), Decimal("0.4")),
}
OPENAI_SHARES = (
    ("input", Decimal("0.35")),
    ("cached input", Decimal("0.10")),
    ("output", Decimal("0.55")),
)
TOKENS_PER_REQUEST = 3000

# Blended USD per million tokens on OpenRouter.
OPENROUTER_RATES = {
    "openai/gpt-5.2": Decimal("5"),
    "anthropic/claude-sonnet-4.6": Decimal("6"),
    "anthropic/claude-sonnet-4": Decimal("6"),
    "x-ai/grok-4.6": Decimal("3"),
    "mistralai/devstral-medium": Decimal("1"),
    "openai/gpt-4o-mini": Decimal("0.4"),
}
OPENROUTER_BYOK_FEE = Decimal("0.05")
PROMPT_SHARE = Decimal("0.75")
CACHED_SHARE = Decimal("0.30")

CURSOR_RATE = Decimal("6")
INCLUDED = "Included in Business"
USAGE_BASED = "Usage-based"


def _tokens(amount: Decimal, price: Decimal) -> int:
    return int((amount / price * MILLION).to_integral_value(rounding=ROUND_DOWN))


def _priced(tokens: int, price: Decimal) -> Decimal:
    return Decimal(tokens) * price / MILLION


def _stamp(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


@dataclass
class AnthropicDay:
    usage: list[dict[str, Any]] = field(default_factory=list)
    cost: list[dict[str, Any]] = field(default_factory=list)
    total_cents: Decimal = Decimal("0")


def anthropic_day(account: Account, version: int, day: date) -> AnthropicDay:
    result = AnthropicDay()
    buckets: dict[tuple[Any, ...], Decimal] = defaultdict(Decimal)
    web: dict[str | None, Decimal] = defaultdict(Decimal)
    for stream in account.streams:
        amount = stream.amount(version, day, account.provider, account.key)
        if amount <= 0:
            continue
        model = stream.model_on(day)
        prices = _anthropic_prices(model, stream)
        tokens: dict[str, int] = {}
        for token_type, share, _label in _anthropic_shares(stream):
            price = prices[token_type]
            tokens[token_type] = _tokens(amount * share, price)
            bucket = (
                stream.workspace,
                model,
                stream.service_tier,
                stream.context_window,
                stream.inference_geo,
                token_type,
            )
            buckets[bucket] += _priced(tokens[token_type], price)
        requests = int(amount * stream.web_search)
        if requests:
            web[stream.workspace] += Decimal(requests) * WEB_SEARCH_PRICE
        result.usage.append(
            {
                "api_key_id": None if stream.login else stream.principal,
                "account_id": stream.principal if stream.login else None,
                "workspace_id": stream.workspace,
                "model": model,
                "service_tier": stream.service_tier,
                "context_window": stream.context_window,
                "inference_geo": stream.inference_geo,
                "uncached_input_tokens": tokens["uncached_input_tokens"],
                "cache_creation": {
                    "ephemeral_5m_input_tokens": tokens["cache_creation.ephemeral_5m_input_tokens"],
                    "ephemeral_1h_input_tokens": tokens.get(
                        "cache_creation.ephemeral_1h_input_tokens", 0
                    ),
                },
                "cache_read_input_tokens": tokens["cache_read_input_tokens"],
                "output_tokens": tokens["output_tokens"],
                "server_tool_use": {"web_search_requests": requests},
            }
        )
    labels = {token_type: label for token_type, _, label in _all_anthropic_types()}
    for (workspace, model, tier, context, geo, token_type), usd in sorted(
        buckets.items(), key=lambda item: tuple(str(part) for part in item[0])
    ):
        amount = cents(usd)
        result.total_cents += amount
        result.cost.append(
            {
                "amount": str(amount),
                "context_window": context,
                "cost_type": "tokens",
                "currency": "USD",
                "description": f"{ANTHROPIC_LABELS[model]} Usage - {labels[token_type]}",
                "inference_geo": geo,
                "model": model,
                "service_tier": tier,
                "token_type": token_type,
                "workspace_id": workspace,
            }
        )
    for workspace, usd in sorted(web.items(), key=lambda item: str(item[0])):
        amount = cents(usd)
        result.total_cents += amount
        result.cost.append(
            {
                "amount": str(amount),
                "context_window": None,
                "cost_type": "web_search",
                "currency": "USD",
                "description": "Web Search",
                "inference_geo": None,
                "model": None,
                "service_tier": None,
                "token_type": None,
                "workspace_id": workspace,
            }
        )
    return result


def _all_anthropic_types() -> tuple[tuple[str, Decimal, str], ...]:
    return (
        *ANTHROPIC_TOKEN_TYPES,
        ("cache_creation.ephemeral_1h_input_tokens", ANTHROPIC_1H_SHARE, "Cache Write (1h)"),
    )


def _anthropic_shares(stream: Stream) -> tuple[tuple[str, Decimal, str], ...]:
    if not stream.cache_1h:
        return ANTHROPIC_TOKEN_TYPES
    shares = list(ANTHROPIC_TOKEN_TYPES)
    write_type, write_share, write_label = shares[3]
    shares[3] = (write_type, write_share - ANTHROPIC_1H_SHARE, write_label)
    return (*shares, _all_anthropic_types()[-1])


def _anthropic_prices(model: str, stream: Stream) -> dict[str, Decimal]:
    uncached, output, write_5m, write_1h, read = ANTHROPIC_PRICES[model]
    factor = BATCH_DISCOUNT if stream.service_tier == "batch" else Decimal("1")
    long = stream.context_window == LONG_CONTEXT
    return {
        "uncached_input_tokens": uncached * factor * (2 if long else 1),
        "output_tokens": output * factor * (Decimal("1.5") if long else 1),
        "cache_read_input_tokens": read * factor * (2 if long else 1),
        "cache_creation.ephemeral_5m_input_tokens": write_5m * factor * (2 if long else 1),
        "cache_creation.ephemeral_1h_input_tokens": write_1h * factor * (2 if long else 1),
    }


@dataclass
class OpenAIDay:
    cost: list[dict[str, Any]] = field(default_factory=list)
    usage: list[dict[str, Any]] = field(default_factory=list)
    activity: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    by_key: dict[tuple[str | None, str | None], Decimal] = field(default_factory=dict)
    total: Decimal = Decimal("0")


def _openai_cost(
    day: OpenAIDay, value: Decimal, line_item: str, project: str | None, key: str | None
) -> None:
    amount = micro(value)
    if amount <= 0:
        return
    day.total += amount
    day.by_key[(project, key)] = day.by_key.get((project, key), Decimal("0")) + amount
    day.cost.append(
        {
            "object": "organization.costs.result",
            "amount": {"value": float(amount), "currency": "usd"},
            "line_item": line_item,
            "project_id": project,
            "api_key_id": key,
        }
    )


def openai_day(account: Account, version: int, day: date) -> OpenAIDay:
    result = OpenAIDay()
    for stream in account.streams:
        amount = stream.amount(version, day, account.provider, account.key)
        if amount <= 0:
            continue
        model = stream.model_on(day)
        uncached_price, cached_price, output_price = OPENAI_PRICES[model]
        prices = {"input": uncached_price, "cached input": cached_price, "output": output_price}
        tokens = {kind: _tokens(amount * share, prices[kind]) for kind, share in OPENAI_SHARES}
        for kind, _ in OPENAI_SHARES:
            _openai_cost(
                result,
                _priced(tokens[kind], prices[kind]),
                f"{model}, {kind}",
                stream.workspace,
                stream.principal,
            )
        requests = int(amount * stream.web_search)
        if requests:
            _openai_cost(
                result,
                Decimal(requests) * WEB_SEARCH_PRICE,
                "web search tool calls",
                stream.workspace,
                stream.principal,
            )
        prompt = tokens["input"] + tokens["cached input"]
        result.usage.append(
            {
                "object": "organization.usage.completions.result",
                "input_tokens": prompt,
                "output_tokens": tokens["output"],
                "input_cached_tokens": tokens["cached input"],
                "input_cache_write_tokens": 0,
                "input_uncached_tokens": tokens["input"],
                "num_model_requests": max(1, (prompt + tokens["output"]) // TOKENS_PER_REQUEST),
                "project_id": stream.workspace,
                "user_id": stream.owner,
                "api_key_id": stream.principal,
                "model": model,
                "batch": None,
                "service_tier": None,
            }
        )
    for activity in account.activities:
        quantity = _activity_quantity(account, version, day, activity)
        result.activity.setdefault(activity.family, []).append(_activity_row(activity, quantity))
        if activity.line_item is not None and activity.unit_price > 0:
            _openai_cost(
                result,
                quantity * activity.unit_price,
                activity.line_item,
                activity.workspace,
                activity.api_key,
            )
    return result


def _activity_quantity(account: Account, version: int, day: date, activity: Activity) -> Decimal:
    if activity.family == "vector_stores":
        # Storage holds over the weekend; it only grows.
        return (activity.quantity * growth(day)).to_integral_value()
    principal = f"{activity.family}:{activity.api_key}"
    return (
        activity.quantity
        * weekday_factor(day)
        * growth(day)
        * noise(version, day, account.provider, account.key, principal)
    ).to_integral_value()


ACTIVITY_QUANTITY_FIELDS = {
    "images": "images",
    "embeddings": "input_tokens",
    "moderations": "input_tokens",
    "audio_speeches": "characters",
    "audio_transcriptions": "seconds",
    "vector_stores": "usage_bytes",
    "code_interpreter_sessions": "num_sessions",
}


def _activity_row(activity: Activity, quantity: Decimal) -> dict[str, Any]:
    row: dict[str, Any] = {
        "object": f"organization.usage.{activity.family}.result",
        ACTIVITY_QUANTITY_FIELDS[activity.family]: int(quantity),
        "project_id": activity.workspace,
    }
    if activity.family != "vector_stores":
        row |= {
            "num_model_requests": max(1, int(quantity * activity.requests_per_unit)),
            "user_id": activity.user,
            "api_key_id": activity.api_key,
            "model": activity.model,
            **activity.detail,
        }
    return row


@dataclass
class OpenRouterDay:
    rows: list[dict[str, Any]] = field(default_factory=list)
    credits: Decimal = Decimal("0")
    byok: Decimal = Decimal("0")
    prompt: int = 0
    completion: int = 0
    cached: int = 0
    reasoning: int = 0
    requests: int = 0


def openrouter_day(
    account: Account, version: int, day: date, names: dict[str, str]
) -> OpenRouterDay:
    result = OpenRouterDay()
    for stream in account.streams:
        amount = micro(stream.amount(version, day, account.provider, account.key))
        if amount <= 0:
            continue
        model = stream.model_on(day)
        credits = micro(amount * OPENROUTER_BYOK_FEE) if stream.byok else amount
        byok = amount if stream.byok else Decimal("0")
        tokens = _tokens(amount, OPENROUTER_RATES[model])
        prompt = int(tokens * PROMPT_SHARE)
        completion = tokens - prompt
        cached = int(prompt * CACHED_SHARE)
        reasoning = int(completion * stream.reasoning)
        requests = max(1, tokens // TOKENS_PER_REQUEST)
        result.credits += credits
        result.byok += byok
        result.prompt += prompt
        result.completion += completion
        result.cached += cached
        result.reasoning += reasoning
        result.requests += requests
        result.rows.append(
            {
                "date__day": day.isoformat(),
                "api_key_id": names[stream.principal],
                "model": model,
                "total_usage": float(credits + byok),
                "credits_usage": float(credits),
                "byok_usage": float(byok),
                "usage_web": 0,
                "tokens_prompt": str(prompt),
                "tokens_completion": str(completion),
                "cached_tokens": str(cached),
                "reasoning_tokens": str(reasoning),
                "request_count": str(requests),
            }
        )
    return result


def openrouter_total_row(day: date, totals: OpenRouterDay, late: Decimal) -> dict[str, Any]:
    credits = totals.credits + late
    return {
        "date__day": day.isoformat(),
        "total_usage": float(credits + totals.byok),
        "credits_usage": float(credits),
        "byok_usage": float(totals.byok),
        "usage_web": 0,
        "tokens_prompt": str(totals.prompt),
        "tokens_completion": str(totals.completion),
        "cached_tokens": str(totals.cached),
        "reasoning_tokens": str(totals.reasoning),
        "request_count": str(totals.requests),
    }


@dataclass(frozen=True)
class CursorEvent:
    email: str
    cents: Decimal
    kind: str
    row: dict[str, Any]


class CursorLedger:
    """Usage events of one Cursor account, day by day: each member's month starts on the
    included allowance and moves to usage-based billing once it is spent."""

    def __init__(self, account: Account, version: int) -> None:
        self.account = account
        self.version = version
        self._days: dict[date, list[CursorEvent]] = {}
        self._spent: dict[tuple[str, date], Decimal] = {}

    def events(self, day: date) -> list[CursorEvent]:
        if day not in self._days:
            if day.day > 1:
                self.events(day - timedelta(days=1))
            self._days[day] = self._build(day)
        return self._days[day]

    def _build(self, day: date) -> list[CursorEvent]:
        month = day.replace(day=1)
        events: list[CursorEvent] = []
        start, _ = _stamp(day)
        for stream in self.account.streams:
            amount = stream.amount(self.version, day, self.account.provider, self.account.key)
            if amount <= 0:
                continue
            email = stream.owner or stream.principal
            count = 2 + int(unit(self.version, day, stream.principal, "events") * 4)
            weights = [
                Decimal("1") + unit(self.version, day, stream.principal, index)
                for index in range(count)
            ]
            spent_key = (email, month)
            for index, weight in enumerate(weights):
                usd = amount * weight / sum(weights)
                event_cents = (usd * 100).quantize(Decimal("0.0001"))
                spent = self._spent.get(spent_key, Decimal("0"))
                kind = INCLUDED if spent < CURSOR_INCLUDED_USD else USAGE_BASED
                self._spent[spent_key] = spent + usd
                tokens = _tokens(usd, CURSOR_RATE)
                at = start + timedelta(hours=9, minutes=37 * index + int(unit(day, index) * 30))
                row: dict[str, Any] = {
                    "timestamp": str(int(at.timestamp() * 1000)),
                    "userEmail": email,
                    "serviceAccountId": "null",
                    "model": stream.model_on(day),
                    "kind": kind,
                    "isChargeable": kind == USAGE_BASED,
                    "tokenUsage": {
                        "inputTokens": tokens // 10,
                        "outputTokens": tokens // 8,
                        "cacheWriteTokens": tokens // 5,
                        "cacheReadTokens": tokens - tokens // 10 - tokens // 8 - tokens // 5,
                        "totalCents": float(event_cents),
                    },
                    "chargedCents": float(event_cents),
                }
                if stream.service_account is not None:
                    row["serviceAccountId"], row["serviceAccountName"] = stream.service_account
                events.append(CursorEvent(email, event_cents, kind, row))
        return events
