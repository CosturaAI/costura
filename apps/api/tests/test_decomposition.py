from datetime import date, timedelta
from decimal import Decimal

from costura.spend.decomposition import decompose

DAY = date(2026, 8, 11)
SAMPLES = [DAY - timedelta(days=7 * k) for k in range(1, 5)]
CENT = Decimal("0.01")


def _sums(result) -> Decimal:
    return result.volume + result.mix + result.price


def test_more_tokens_at_the_same_prices_is_all_volume() -> None:
    by_day = {d: {"sonnet": (Decimal("10"), 1000)} for d in SAMPLES}
    by_day[DAY] = {"sonnet": (Decimal("30"), 3000)}
    result = decompose(by_day, DAY, SAMPLES)
    assert result is not None
    assert result.change == Decimal("20")
    assert (result.volume, result.mix, result.price) == (Decimal("20"), Decimal("0"), Decimal("0"))


def test_the_same_tokens_at_a_higher_price_is_all_price() -> None:
    by_day = {d: {"sonnet": (Decimal("10"), 1000)} for d in SAMPLES}
    by_day[DAY] = {"sonnet": (Decimal("15"), 1000)}
    result = decompose(by_day, DAY, SAMPLES)
    assert result is not None
    assert result.price == Decimal("5") and result.volume == 0 and result.mix == 0


def test_a_switch_to_a_dearer_model_is_mix_and_names_the_day() -> None:
    by_day = {d: {"sonnet": (Decimal("10"), 1000)} for d in SAMPLES}
    for offset in (3, 2, 1):
        by_day[DAY - timedelta(days=offset)] = {"sonnet": (Decimal("10"), 1000)}
    switched = {"sonnet": (Decimal("2"), 200), "opus": (Decimal("40"), 800)}
    by_day[DAY - timedelta(days=1)] = switched
    by_day[DAY] = switched
    result = decompose(by_day, DAY, SAMPLES)
    assert result is not None
    assert result.top_model == "opus"
    assert (result.top_share_baseline, result.top_share_day) == (Decimal("0"), Decimal("0.8"))
    assert result.switch_day == DAY - timedelta(days=1)
    assert result.volume == 0 and result.mix == result.change == Decimal("32")
    assert abs(_sums(result) - result.change) < CENT


def test_no_baseline_days_or_tokens_gives_no_split() -> None:
    assert decompose({DAY: {"sonnet": (Decimal("1"), 10)}}, DAY, []) is None
    assert decompose({DAY: {"sonnet": (Decimal("1"), 10)}}, DAY, SAMPLES) is None
