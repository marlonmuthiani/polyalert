import json

import pytest

from polyalert.polymarket.rest import MarketNotFound, PolymarketRest


def _market_payload(slug="m1", title="Q?", closed=False, active=True):
    return {
        "slug": slug,
        "question": title,
        "outcomes": json.dumps(["Yes", "No"]),
        "clobTokenIds": json.dumps(["tok-yes", "tok-no"]),
        "closed": closed,
        "active": active,
    }


async def test_get_market_by_slug(httpx_mock):
    httpx_mock.add_response(
        url="https://gamma-api.polymarket.com/markets?slug=foo",
        json=[_market_payload(slug="foo", title="Will it rain?")],
    )
    client = PolymarketRest("https://gamma-api.polymarket.com")
    m = await client.get_market("foo")
    await client.close()
    assert m.slug == "foo"
    assert m.title == "Will it rain?"
    assert [o.label for o in m.outcomes] == ["Yes", "No"]
    assert [o.token_id for o in m.outcomes] == ["tok-yes", "tok-no"]
    assert m.closed is False


async def test_get_market_not_found(httpx_mock):
    httpx_mock.add_response(
        url="https://gamma-api.polymarket.com/markets?slug=nope",
        json=[],
    )
    client = PolymarketRest("https://gamma-api.polymarket.com")
    with pytest.raises(MarketNotFound):
        await client.get_market("nope")
    await client.close()


async def test_get_event_with_markets(httpx_mock):
    httpx_mock.add_response(
        url="https://gamma-api.polymarket.com/events?slug=ev",
        json=[{
            "slug": "ev",
            "title": "Event",
            "markets": [
                _market_payload(slug="m-a", title="A?"),
                _market_payload(slug="m-b", title="B?", closed=True),
            ],
        }],
    )
    client = PolymarketRest("https://gamma-api.polymarket.com")
    e = await client.get_event("ev")
    await client.close()
    assert e.slug == "ev"
    assert [m.slug for m in e.markets] == ["m-a", "m-b"]
    assert e.markets[1].closed is True


async def test_market_treats_inactive_as_closed(httpx_mock):
    httpx_mock.add_response(
        url="https://gamma-api.polymarket.com/markets?slug=x",
        json=[_market_payload(slug="x", active=False)],
    )
    client = PolymarketRest("https://gamma-api.polymarket.com")
    m = await client.get_market("x")
    await client.close()
    assert m.closed is True
