from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

SWITCH_SHARE = Decimal("0.30")
SWITCH_LOOKBACK_DAYS = 14

ModelDay = Mapping[str, tuple[Decimal, int]]


@dataclass(frozen=True)
class Decomposition:
    change: Decimal
    volume: Decimal
    mix: Decimal
    price: Decimal
    top_model: str
    top_share_baseline: Decimal
    top_share_day: Decimal
    switch_day: date | None


def decompose(
    by_day: Mapping[date, ModelDay], day: date, sample_days: Sequence[date]
) -> Decomposition | None:
    if not sample_days:
        return None
    count = Decimal(len(sample_days))
    base_amount: dict[str, Decimal] = {}
    base_tokens: dict[str, Decimal] = {}
    for sample_day in sample_days:
        for model, (amount, tokens) in by_day.get(sample_day, {}).items():
            base_amount[model] = base_amount.get(model, Decimal("0")) + amount / count
            base_tokens[model] = base_tokens.get(model, Decimal("0")) + Decimal(tokens) / count
    today = by_day.get(day, {})
    day_amount = {model: amount for model, (amount, _) in today.items()}
    day_tokens = {model: Decimal(tokens) for model, (_, tokens) in today.items()}
    total_base_tokens = sum(base_tokens.values(), Decimal("0"))
    total_day_tokens = sum(day_tokens.values(), Decimal("0"))
    if total_base_tokens <= 0 or total_day_tokens <= 0 or not day_amount:
        return None
    total_base = sum(base_amount.values(), Decimal("0"))
    total_day = sum(day_amount.values(), Decimal("0"))

    def day_price(model: str) -> Decimal:
        tokens = day_tokens.get(model, Decimal("0"))
        return day_amount.get(model, Decimal("0")) / tokens if tokens > 0 else Decimal("0")

    def base_price(model: str) -> Decimal:
        tokens = base_tokens.get(model, Decimal("0"))
        return base_amount[model] / tokens if tokens > 0 else day_price(model)

    models = set(base_tokens) | set(day_tokens)
    base_share = {m: base_tokens.get(m, Decimal("0")) / total_base_tokens for m in models}
    day_share = {m: day_tokens.get(m, Decimal("0")) / total_day_tokens for m in models}
    volume = (total_day_tokens - total_base_tokens) * total_base / total_base_tokens
    mix = total_day_tokens * sum(
        ((day_share[m] - base_share[m]) * base_price(m) for m in models), Decimal("0")
    )
    price = total_day_tokens * sum(
        (day_share[m] * (day_price(m) - base_price(m)) for m in models if day_share[m] > 0),
        Decimal("0"),
    )
    top_model = max(day_amount, key=lambda m: (day_amount[m], m))
    return Decomposition(
        change=total_day - total_base,
        volume=volume,
        mix=mix,
        price=price,
        top_model=top_model,
        top_share_baseline=base_share[top_model],
        top_share_day=day_share[top_model],
        switch_day=switch_day(by_day, day, top_model, base_share[top_model]),
    )


def switch_day(
    by_day: Mapping[date, ModelDay], day: date, model: str, baseline_share: Decimal
) -> date | None:
    for candidate in sorted(d for d in by_day if 0 <= (day - d).days < SWITCH_LOOKBACK_DAYS):
        models = by_day[candidate]
        tokens = sum((Decimal(t) for _, t in models.values()), Decimal("0"))
        if tokens <= 0:
            continue
        share = Decimal(models.get(model, (Decimal("0"), 0))[1]) / tokens
        if share - baseline_share >= SWITCH_SHARE:
            return candidate
    return None
