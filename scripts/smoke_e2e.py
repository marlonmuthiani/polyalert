"""End-to-end smoke test against the real Polymarket APIs.

Simulates the exact data path that the Telegram bot exercises during
alert creation, so we can verify the wiring works before redeploying.

Usage: python scripts/smoke_e2e.py <event-or-market-url>
"""

import asyncio
import sys

from polyalert.engine import current_price
from polyalert.models import PriceTick
from polyalert.polymarket.rest import PolymarketRest
from polyalert.polymarket.url import parse_polymarket_url
from polyalert.polymarket.wss import WSSManager, open_polymarket_connection


async def _smoke(url: str) -> int:
    print(f"INPUT URL: {url}")
    event_slug, market_slug = parse_polymarket_url(url)
    print(f"  parsed: event_slug={event_slug!r}  market_slug={market_slug!r}")

    rest = PolymarketRest("https://gamma-api.polymarket.com")
    try:
        if market_slug:
            market = await rest.get_market(market_slug)
            print(f"  -> direct market: {market.title!r} closed={market.closed}")
        else:
            assert event_slug is not None
            event = await rest.get_event(event_slug)
            print(f"  -> event: {event.title!r} with {len(event.markets)} markets")
            open_markets = [m for m in event.markets if not m.closed]
            print(f"     open: {len(open_markets)}")
            if not open_markets:
                print("FAIL: no open markets")
                return 1
            market = open_markets[0]
            print(f"     pick first open: {market.title!r}")

        if not market.outcomes:
            print("FAIL: market has no outcomes")
            return 1
        print("  outcomes:")
        for o in market.outcomes:
            print(f"     - {o.label!r}  token_id={o.token_id[:20]}…  ({len(o.token_id)} chars)")

        outcome = market.outcomes[0]
        print(f"  pick outcome: {outcome.label!r}")

        # The bug we just fixed: /price was being requested from the wrong host.
        bid = await rest.get_price(outcome.token_id, "BUY")
        ask = await rest.get_price(outcome.token_id, "SELL")
        print(f"  CLOB /price BUY={bid}  SELL={ask}")
        if bid <= 0 or ask <= 0:
            print("FAIL: degenerate price")
            return 1

        tick = PriceTick(asset_id=outcome.token_id, bid=bid, ask=ask)
        for side in ("bid", "ask", "mid"):
            print(f"     current_price({side}) = {current_price(side, tick):.4f}")
    finally:
        await rest.close()

    # Now exercise WSS — connect, subscribe to the chosen token, wait for
    # at least one tick or 8s timeout. This mirrors what AlertEngine does
    # when an alert is registered.
    received: list[PriceTick] = []
    wss = WSSManager(
        connect=lambda: open_polymarket_connection(
            "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        ),
        stale_timeout=300.0,
    )
    wss.on_tick = received.append
    await wss.start()
    await wss.subscribe(outcome.token_id)
    print("  WSS subscribed; waiting up to 8s for a tick...")
    for _ in range(80):
        await asyncio.sleep(0.1)
        if received:
            break
    await wss.stop()

    if not received:
        print("FAIL: no WSS tick received within 8s")
        return 1
    t0 = received[0]
    print(f"  WSS tick: bid={t0.bid:.4f} ask={t0.ask:.4f} mid={t0.mid:.4f}")
    print(f"  total ticks during window: {len(received)}")

    print("OK: full end-to-end path works")
    return 0


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else (
        "polymarket.com/event/hantavirus-pandemic-in-2026"
    )
    rc = asyncio.run(_smoke(url))
    sys.exit(rc)


if __name__ == "__main__":
    main()
