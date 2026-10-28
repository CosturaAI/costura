"""Turn OpenRouter analytics rows into Costura cost and usage lines.

One analytics row is `(day, key, model)` with spend and token counters. The cost Costura
stores is what OpenRouter bills: `credits_usage`. `total_usage` also includes the BYOK
inference cost paid to the underlying provider (`byok_usage`); that money is billed by the
provider and, when the provider is connected, its own connector already counts it.
OpenRouter prices per key, so the same row produces both records:

- a `CostLine` at the workspace grain (`description="credits"`, `cost_type="tokens"`, no
  token type), which `reconcile` compares with the ungrouped control total;
- a `UsageLine` carrying the key, its creator, the token counters, the row's billed `amount`
  and the informational `byok_amount`; `allocate` copies `amount` as the provider-attributed
  allocation.

The API resolves `api_key_id` to the key *name*. `KeyDirectory` maps names back to the key
hash, workspace and creator through the stored inventory; a name without a current key (a
deleted or renamed key) keeps the name as its id, so the total still reconciles.

Token subsets: `cached_tokens` is part of `tokens_prompt` and `reasoning_tokens` part of
`tokens_completion`; the lines store the disjoint parts so `total_tokens` does not double count.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import ProviderApiKey
from costura.providers.lines import (
    CostLine,
    NormalizeError,
    UsageLine,
    aggregate_cost_lines,
    aggregate_usage_lines,
)
from costura.providers.openrouter import PROVIDER

CURRENCY = "USD"
DESCRIPTION = "credits"
COST_TYPE = "tokens"
SERVICE_TIER = "standard"
BILLED_FIELD = "credits_usage"
BYOK_FIELD = "byok_usage"


@dataclass(frozen=True)
class KeyRef:
    hash: str
    workspace_id: str | None
    creator_id: str | None


@dataclass(frozen=True)
class KeyDirectory:
    """Key name -> current key. Names that map to more than one key are ambiguous and are
    treated like unknown names."""

    by_name: dict[str, KeyRef]

    @classmethod
    def load(cls, session: Session, account_id: int) -> KeyDirectory:
        rows = session.execute(
            select(
                ProviderApiKey.name,
                ProviderApiKey.external_id,
                ProviderApiKey.workspace_external_id,
                ProviderApiKey.created_by_external_id,
            ).where(
                ProviderApiKey.provider_account_id == account_id,
                ProviderApiKey.provider == PROVIDER,
                ProviderApiKey.missing_since.is_(None),
            )
        ).all()
        return cls.from_rows(rows)

    @classmethod
    def from_rows(cls, rows: Iterable[tuple[str, str, str | None, str | None]]) -> KeyDirectory:
        by_name: dict[str, KeyRef | None] = {}
        for name, external_id, workspace_id, creator_id in rows:
            if name in by_name:
                by_name[name] = None
            else:
                by_name[name] = KeyRef(external_id, workspace_id, creator_id)
        return cls({name: ref for name, ref in by_name.items() if ref is not None})

    def resolve(self, name: str) -> KeyRef:
        return self.by_name.get(name) or KeyRef(name, None, None)


def parse_day(value: Any) -> tuple[datetime, datetime]:
    if not isinstance(value, str):
        raise NormalizeError(f"date__day is not a string: {value!r}")
    try:
        day = datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise NormalizeError(f"date__day is not YYYY-MM-DD: {value!r}") from exc
    return day, day + timedelta(days=1)


def _count(row: dict[str, Any], field: str) -> int:
    value = row.get(field)
    if value is None:
        return 0
    if isinstance(value, bool):
        raise NormalizeError(f"{field} is not a count: {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise NormalizeError(f"{field} is not a count: {value!r}") from exc


def _money(row: dict[str, Any], field: str) -> Decimal:
    value = row.get(field)
    if value is None:
        return Decimal("0")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise NormalizeError(f"{field} is not a number: {value!r}")
    # `str()` keeps the shortest repr of the double the API sent; Decimal(float) would not.
    try:
        amount = Decimal(str(value))
    except ArithmeticError as exc:
        raise NormalizeError(f"{field} is not a number: {value!r}") from exc
    if not amount.is_finite():
        raise NormalizeError(f"{field} is not a finite number: {value!r}")
    return amount


def _text(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise NormalizeError(f"{field} is missing")
    return value


def billed_amount(row: dict[str, Any]) -> Decimal:
    """What OpenRouter billed for the row: `credits_usage`."""
    if BILLED_FIELD not in row:
        raise NormalizeError(f"row has no {BILLED_FIELD}")
    return _money(row, BILLED_FIELD)


def byok_amount(row: dict[str, Any]) -> Decimal | None:
    """BYOK inference cost paid to the underlying provider; None when the row lacks it."""
    if BYOK_FIELD not in row:
        return None
    return _money(row, BYOK_FIELD)


def lines_from_rows(
    rows: Iterable[dict[str, Any]], directory: KeyDirectory
) -> tuple[list[CostLine], list[UsageLine]]:
    """Cost and usage lines of the rows of one analytics page, not yet aggregated."""
    cost: list[CostLine] = []
    usage: list[UsageLine] = []
    for row in rows:
        period_start, period_end = parse_day(row.get("date__day"))
        key = directory.resolve(_text(row, "api_key_id"))
        model = _text(row, "model")
        amount = billed_amount(row)
        byok = byok_amount(row)
        prompt = _count(row, "tokens_prompt")
        completion = _count(row, "tokens_completion")
        cached = min(_count(row, "cached_tokens"), prompt)
        reasoning = min(_count(row, "reasoning_tokens"), completion)
        cost.append(
            CostLine(
                period_start=period_start,
                period_end=period_end,
                workspace_id=key.workspace_id,
                description=DESCRIPTION,
                cost_type=COST_TYPE,
                model=model,
                token_type=None,
                service_tier=SERVICE_TIER,
                context_window=None,
                inference_geo=None,
                amount=amount,
                currency=CURRENCY,
                raw_amount_minor=str(row.get(BILLED_FIELD)),
                provider=PROVIDER,
            )
        )
        usage.append(
            UsageLine(
                period_start=period_start,
                period_end=period_end,
                api_key_id=key.hash,
                account_id=key.creator_id,
                workspace_id=key.workspace_id,
                model=model,
                service_tier=SERVICE_TIER,
                context_window=None,
                inference_geo=None,
                uncached_input_tokens=prompt - cached,
                cache_creation_5m_tokens=0,
                cache_creation_1h_tokens=0,
                cache_read_tokens=cached,
                output_tokens=completion - reasoning,
                web_search_requests=0,
                provider=PROVIDER,
                reasoning_tokens=reasoning,
                request_count=_count(row, "request_count"),
                amount=amount,
                currency=CURRENCY,
                byok_amount=byok,
            )
        )
    return cost, usage


def total_amounts(rows: Iterable[dict[str, Any]]) -> list[Decimal]:
    return [billed_amount(row) for row in rows]


__all__ = [
    "CURRENCY",
    "KeyDirectory",
    "KeyRef",
    "aggregate_cost_lines",
    "aggregate_usage_lines",
    "billed_amount",
    "byok_amount",
    "lines_from_rows",
    "parse_day",
    "total_amounts",
]
