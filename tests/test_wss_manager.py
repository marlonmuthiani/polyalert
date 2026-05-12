import asyncio

import pytest

from polyalert.models import PriceTick
from polyalert.polymarket.wss import WSSManager


class FakeConn:
    def __init__(self):
        self.sent: list[dict] = []
        self.incoming: asyncio.Queue[dict] = asyncio.Queue()
        self.closed = False

    async def send(self, msg: dict) -> None:
        self.sent.append(msg)

    async def recv(self) -> dict:
        msg = await self.incoming.get()
        if msg is None:
            raise ConnectionError("closed")
        return msg

    async def close(self) -> None:
        self.closed = True
        await self.incoming.put(None)


def test_subscribe_increments_refcount_and_sends_once():
    async def run():
        conn = FakeConn()
        mgr = WSSManager(connect=lambda: conn)
        await mgr.start()
        await mgr.subscribe("tok1")
        await mgr.subscribe("tok1")
        # Allow loop to send subscribe message
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert any(m.get("type") == "market" and "tok1" in m.get("assets_ids", [])
                   for m in conn.sent)
        # Only one subscribe message for tok1
        sub_count = sum(
            1 for m in conn.sent
            if m.get("type") == "market" and "tok1" in m.get("assets_ids", [])
        )
        assert sub_count == 1
        await mgr.stop()

    asyncio.run(run())


def test_subscribing_to_second_asset_resyncs_full_set():
    """Polymarket WSS treats a `market` subscribe as a SET-REPLACE: the second
    message overrides the first. Verified empirically against
    wss-subscriptions-clob.polymarket.com on 2026-05-08. We therefore re-send
    the full active asset set on every transition."""
    async def run():
        conn = FakeConn()
        mgr = WSSManager(connect=lambda: conn)
        await mgr.start()
        await mgr.subscribe("tok-A")
        await mgr.subscribe("tok-B")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        market_msgs = [m for m in conn.sent if m.get("type") == "market"]
        # First subscribe sent {assets_ids: [tok-A]}, second sent
        # {assets_ids: [tok-A, tok-B]} — the second is the one Polymarket
        # actually honors and must contain BOTH tokens.
        last = market_msgs[-1]
        assert set(last["assets_ids"]) == {"tok-A", "tok-B"}, (
            f"last subscribe must batch both: got {last}"
        )
        await mgr.stop()

    asyncio.run(run())


def test_unsubscribe_when_other_refs_remain_resyncs_remaining():
    """When one of multiple subscriptions goes to zero, the server must learn
    the new set so it stops pushing the removed asset."""
    async def run():
        conn = FakeConn()
        mgr = WSSManager(connect=lambda: conn)
        await mgr.start()
        await mgr.subscribe("tok-A")
        await mgr.subscribe("tok-B")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await mgr.unsubscribe("tok-A")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        market_msgs = [m for m in conn.sent if m.get("type") == "market"]
        last = market_msgs[-1]
        assert last["assets_ids"] == ["tok-B"], (
            f"after unsubscribing tok-A, only tok-B should remain: {last}"
        )
        await mgr.stop()

    asyncio.run(run())


def test_unsubscribe_to_zero_does_not_send_empty_set():
    """When all refs drop to zero we don't send `assets_ids: []` — Polymarket
    has no documented `clear all` and the server keeps the last set; we just
    let the connection idle. The next subscribe will overwrite cleanly."""
    async def run():
        conn = FakeConn()
        mgr = WSSManager(connect=lambda: conn)
        await mgr.start()
        await mgr.subscribe("tok1")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        sent_after_subscribe = list(conn.sent)
        await mgr.unsubscribe("tok1")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # No new messages after the final unsubscribe.
        assert conn.sent == sent_after_subscribe
        await mgr.stop()

    asyncio.run(run())


def test_incoming_book_emitted_as_pricetick():
    async def run():
        conn = FakeConn()
        mgr = WSSManager(connect=lambda: conn)
        ticks: list[PriceTick] = []
        mgr.on_tick = lambda t: ticks.append(t)
        await mgr.start()
        await mgr.subscribe("tok-x")
        await conn.incoming.put({
            "event_type": "book",
            "asset_id": "tok-x",
            "bids": [{"price": "0.40", "size": "100"}],
            "asks": [{"price": "0.42", "size": "120"}],
        })
        await asyncio.sleep(0.05)
        assert len(ticks) == 1
        assert ticks[0].asset_id == "tok-x"
        assert ticks[0].bid == pytest.approx(0.40)
        assert ticks[0].ask == pytest.approx(0.42)
        await mgr.stop()

    asyncio.run(run())


def test_reconnect_re_subscribes_active_assets(monkeypatch):
    async def run():
        conns: list[FakeConn] = []

        def factory():
            c = FakeConn()
            conns.append(c)
            return c

        # Skip backoff in tests
        from polyalert.polymarket import wss as wss_mod
        monkeypatch.setattr(wss_mod, "_backoff_seconds", lambda attempt: 0)

        mgr = WSSManager(connect=factory)
        await mgr.start()
        await mgr.subscribe("tok-A")
        await mgr.subscribe("tok-B")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        # Force first conn to fail by closing it
        await conns[0].close()
        # Give recv-loop time to detect and reconnect
        await asyncio.sleep(0.1)
        await asyncio.sleep(0.1)

        assert len(conns) >= 2
        # Second connection got a SINGLE batched re-subscribe with both tokens
        # (NOT one message per token — Polymarket would set-replace).
        market_msgs = [m for m in conns[1].sent if m.get("type") == "market"]
        assert market_msgs, "no subscribe sent after reconnect"
        assert set(market_msgs[0]["assets_ids"]) == {"tok-A", "tok-B"}, (
            f"reconnect must re-subscribe in a single batched message: {market_msgs}"
        )
        await mgr.stop()

    asyncio.run(run())


def test_incoming_list_emits_multiple_ticks():
    async def run():
        conn = FakeConn()
        mgr = WSSManager(connect=lambda: conn)
        ticks: list[PriceTick] = []
        mgr.on_tick = lambda t: ticks.append(t)
        await mgr.start()
        await mgr.subscribe("a")
        await mgr.subscribe("b")
        await conn.incoming.put([
            {"event_type": "book", "asset_id": "a",
             "bids": [{"price": "0.4"}], "asks": [{"price": "0.5"}]},
            {"event_type": "book", "asset_id": "b",
             "bids": [{"price": "0.3"}], "asks": [{"price": "0.4"}]},
        ])
        await asyncio.sleep(0.05)
        ids = {t.asset_id for t in ticks}
        assert ids == {"a", "b"}
        await mgr.stop()

    asyncio.run(run())


@pytest.mark.skip(reason="timing-sensitive")
def test_watchdog_closes_stale_connection(monkeypatch):
    async def run():
        from polyalert.polymarket import wss as wss_mod
        conns: list[FakeConn] = []

        def factory():
            c = FakeConn()
            conns.append(c)
            return c

        monkeypatch.setattr(wss_mod, "_backoff_seconds", lambda a: 0)

        mgr = WSSManager(connect=factory, stale_timeout=0.05)
        await mgr.start()
        await mgr.subscribe("tok-stale")
        # Send one message so _last_message_at gets set
        await conns[0].incoming.put({
            "event_type": "book", "asset_id": "tok-stale",
            "bids": [{"price": "0.4"}], "asks": [{"price": "0.5"}],
        })
        await asyncio.sleep(0.02)
        # Now wait for staleness watchdog to trigger
        await asyncio.sleep(0.5)
        # Should have reconnected at least once
        assert len(conns) >= 2
        await mgr.stop()

    asyncio.run(run())
