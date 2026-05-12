import pytest

from polyalert.engine import current_price, should_fire
from polyalert.models import Alert, PriceTick


def _alert(*, side, direction, threshold) -> Alert:
    return Alert(
        id=1, user_id=1, market_slug="m", market_title="t", asset_id="tok",
        outcome_label="Yes", side=side, direction=direction,
        threshold=threshold, created_at="2026-05-08",
    )


@pytest.mark.parametrize("side,bid,ask,expected", [
    ("bid", 0.4, 0.5, 0.4),
    ("ask", 0.4, 0.5, 0.5),
    ("mid", 0.4, 0.5, 0.45),
])
def test_current_price(side, bid, ask, expected):
    tick = PriceTick("tok", bid, ask)
    assert current_price(side, tick) == pytest.approx(expected)


def test_above_fires_when_price_meets_threshold():
    tick = PriceTick("tok", 0.55, 0.56)
    assert should_fire(_alert(side="bid", direction="above", threshold=0.55), tick)


def test_above_does_not_fire_when_below():
    tick = PriceTick("tok", 0.50, 0.51)
    assert not should_fire(_alert(side="bid", direction="above", threshold=0.55), tick)


def test_below_fires_when_price_at_threshold():
    tick = PriceTick("tok", 0.30, 0.31)
    assert should_fire(_alert(side="ask", direction="below", threshold=0.31), tick)


def test_below_does_not_fire_when_above():
    tick = PriceTick("tok", 0.50, 0.51)
    assert not should_fire(_alert(side="ask", direction="below", threshold=0.31), tick)


def test_other_asset_id_never_fires():
    tick = PriceTick("OTHER", 0.99, 1.00)
    assert not should_fire(
        _alert(side="ask", direction="above", threshold=0.5),
        tick,
    )
