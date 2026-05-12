import pytest

from polyalert.polymarket.url import InvalidURL, parse_polymarket_url


def test_event_with_market():
    e, m = parse_polymarket_url(
        "https://polymarket.com/event/will-the-us-confirm-that-aliens-exist-before-2027"
        "/will-the-us-confirm-that-aliens-exist-by-may-31"
    )
    assert e == "will-the-us-confirm-that-aliens-exist-before-2027"
    assert m == "will-the-us-confirm-that-aliens-exist-by-may-31"


def test_event_only():
    e, m = parse_polymarket_url("https://polymarket.com/event/some-event")
    assert e == "some-event"
    assert m is None


def test_market_path():
    e, m = parse_polymarket_url("https://polymarket.com/market/some-market")
    assert e is None
    assert m == "some-market"


def test_strips_query_and_fragment():
    e, m = parse_polymarket_url("https://polymarket.com/event/x/y?ref=tg#anchor")
    assert e == "x"
    assert m == "y"


def test_accepts_http_and_no_scheme():
    e, _m = parse_polymarket_url("polymarket.com/event/x")
    assert e == "x"


@pytest.mark.parametrize("bad", [
    "",
    "not a url",
    "https://example.com/event/x",
    "https://polymarket.com/",
    "https://polymarket.com/profile/foo",
])
def test_invalid_url_raises(bad):
    with pytest.raises(InvalidURL):
        parse_polymarket_url(bad)


def test_rejects_polymarket_com_lookalikes():
    with pytest.raises(InvalidURL):
        parse_polymarket_url("https://evilpolymarket.com/event/x")
