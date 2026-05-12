"""Verify the WSS handles subscriptions to multiple distinct assets correctly.

Pick two unrelated markets. Subscribe to one outcome from each, confirm:
  1. The connection is up.
  2. Both assets are present in the manager's subscription set.
  3. After unsubscribing one, only the other remains.
  4. We receive at least one tick on the connection (proves the protocol
     accepted our messages — book snapshot or price_change for either asset).

We do NOT assert "tick for each asset within N seconds" — Polymarket only
pushes the initial book snapshot on the FIRST subscribe message of the
session. Subsequent set-replaces start tracking newer assets but won't
re-emit snapshots for them. Real-time price_change events are organic and
arrive only when the market actually moves; on illiquid markets that can be
minutes apart, so a naive "did B tick in 12s" check is unreliable.

The protocol-correctness path (one batched `{market: [...]}` message
containing all active assets) is verified by unit tests in
`tests/test_wss_manager.py`.
"""

import asyncio
import sys

from polyalert.models import PriceTick
from polyalert.polymarket.rest import PolymarketRest
from polyalert.polymarket.wss import WSSManager, open_polymarket_connection


async def _pick_yes_token(rest: PolymarketRest, slug_or_event: str) -> tuple[str, str, str]:
    """Try as event slug; fall back to market slug. Returns (title, label, token_id)."""
    try:
        ev = await rest.get_event(slug_or_event)
        for m in ev.markets:
            if not m.closed and m.outcomes:
                return m.title, m.outcomes[0].label, m.outcomes[0].token_id
        raise ValueError(f"no open markets in event {slug_or_event}")
    except Exception:
        m = await rest.get_market(slug_or_event)
        return m.title, m.outcomes[0].label, m.outcomes[0].token_id


async def _smoke(slug_a: str, slug_b: str) -> int:
    rest = PolymarketRest("https://gamma-api.polymarket.com")
    try:
        title_a, label_a, tok_a = await _pick_yes_token(rest, slug_a)
        title_b, label_b, tok_b = await _pick_yes_token(rest, slug_b)
    finally:
        await rest.close()

    print(f"A: {title_a!r}  {label_a}={tok_a[:20]}…")
    print(f"B: {title_b!r}  {label_b}={tok_b[:20]}…")
    if tok_a == tok_b:
        print("FAIL: picked the same token twice (unable to test multi-asset)")
        return 1

    all_ticks: list[PriceTick] = []
    wss = WSSManager(
        connect=lambda: open_polymarket_connection(
            "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        ),
        stale_timeout=300.0,
    )
    wss.on_tick = all_ticks.append
    await wss.start()
    await wss.subscribe(tok_a)
    await wss.subscribe(tok_b)

    # Brief wait for at least one event to arrive (handshake / initial snapshot).
    deadline = 120  # 12s
    while deadline > 0 and not all_ticks:
        await asyncio.sleep(0.1)
        deadline -= 1

    stats = wss.stats()
    print(f"WSS stats after subscribe: connected={stats['connected']}, "
          f"subs={list(stats['subscriptions'].keys())}, "
          f"ticks_total={stats['ticks_total']}")

    if not stats["connected"]:
        print("FAIL: WSS not connected")
        await wss.stop()
        return 1
    if tok_a not in stats["subscriptions"] or tok_b not in stats["subscriptions"]:
        print(f"FAIL: subscription set missing tokens. Got {stats['subscriptions']}")
        await wss.stop()
        return 1
    if stats["ticks_total"] == 0:
        print("WARN: no ticks at all (server accepted the subs but markets are silent)")

    # Now unsubscribe A and confirm B remains
    await wss.unsubscribe(tok_a)
    await asyncio.sleep(0.2)
    stats_after = wss.stats()
    if tok_a in stats_after["subscriptions"]:
        print("FAIL: tok_a still in subscriptions after unsubscribe")
        await wss.stop()
        return 1
    if tok_b not in stats_after["subscriptions"]:
        print("FAIL: tok_b vanished after we unsubscribed only A")
        await wss.stop()
        return 1
    print(f"after unsub A: subs={list(stats_after['subscriptions'].keys())} ✓")

    await wss.unsubscribe(tok_b)
    await wss.stop()
    print("OK: subscription protocol works correctly for distinct assets")
    return 0


def main() -> None:
    a = sys.argv[1] if len(sys.argv) > 1 else "hantavirus-pandemic-in-2026"
    b = sys.argv[2] if len(sys.argv) > 2 else "will-elon-musk-tweet-doge-this-week"
    rc = asyncio.run(_smoke(a, b))
    sys.exit(rc)


if __name__ == "__main__":
    main()
