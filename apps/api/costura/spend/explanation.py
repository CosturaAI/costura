from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from costura.spend.decomposition import Decomposition

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Driver:
    kind: str
    label: str
    share: Decimal | None


def _usd(value: Decimal) -> str:
    return f"{abs(value).quantize(CENT):,.2f} USD"


def _percent(value: Decimal) -> str:
    return f"{abs(value).quantize(Decimal('1')):,}%"


def explain(
    *,
    kind: str,
    label: str,
    impact: Decimal,
    impact_percent: Decimal | None,
    actual: Decimal,
    impact_share: Decimal | None,
    drivers: Sequence[Driver],
    split: Decomposition | None = None,
) -> str:
    if kind == "new_principal":
        sentence = f"{label} is new: {_usd(actual)} on its first day"
        if impact_share is not None:
            sentence += f", {_percent(impact_share * 100)} of the month's spend to date"
        return sentence + "."
    falling = kind == "drop"
    direction = "less" if falling else "more"
    sentence = f"{label} spent {_usd(impact)} {direction} than expected"
    if impact_percent is not None:
        sentence += f" ({_percent(impact_percent)} {'under' if falling else 'over'})"
    principal = next((d for d in drivers if d.kind != "model"), None)
    model = next((d for d in drivers if d.kind == "model"), None)
    change = "drop" if falling else "increase"
    if principal is not None:
        sentence += f"; {principal.label}"
        if principal.share is not None:
            sentence += f" accounts for {_percent(principal.share * 100)} of the {change}"
        else:
            sentence += " moved the most"
        if model is not None:
            sentence += f", on {model.label}"
    elif model is not None:
        sentence += f"; {model.label}"
        if model.share is not None:
            sentence += f" accounts for {_percent(model.share * 100)} of the {change}"
    if split is not None and split.switch_day is not None:
        sentence += (
            f"; {split.top_model} rose to {_percent(split.top_share_day * 100)} of tokens"
            f" from {_percent(split.top_share_baseline * 100)} on {split.switch_day.isoformat()}"
        )
    return sentence + "."
