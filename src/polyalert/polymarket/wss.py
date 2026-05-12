import asyncio
import contextlib
import json as _json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Protocol, Union

import websockets

from polyalert.models import PriceTick

log = logging.getLogger(__name__)

OnTick = Callable[[PriceTick], None]
ConnectFn = Callable[[], Union[Awaitable["WSSConnection"], "WSSConnection"]]


def _backoff_seconds(attempt: int) -> float:
    return min(60.0, 2 ** (attempt - 1))


class WSSConnection(Protocol):
    async def send(self, msg: dict) -> None: ...
    async def recv(self) -> dict | list: ...
    async def close(self) -> None: ...


class WSSManager:
    """Maintains a single Polymarket WSS connection with ref-counted subscriptions.

    Reconnection with exponential backoff is handled in `_run`.
    """

    def __init__(self, connect: ConnectFn, stale_timeout: float = 300.0):
        self._connect = connect
        self._conn: WSSConnection | None = None
        self._refs: dict[str, int] = {}
        self._send_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._main_task: asyncio.Task | None = None
        self._send_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._stopping = False
        self._stale_timeout = stale_timeout
        self._last_message_at: float | None = None
        # Observability counters
        self._connected = False
        self._connects_total = 0
        self._reconnects_total = 0
        self._ticks_total = 0
        self.on_tick: OnTick | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    def stats(self) -> dict:
        last_age = (
            time.monotonic() - self._last_message_at
            if self._last_message_at is not None
            else None
        )
        return {
            "connected": self._connected,
            "connects_total": self._connects_total,
            "reconnects_total": self._reconnects_total,
            "subscriptions": dict(self._refs),
            "ticks_total": self._ticks_total,
            "last_message_age_seconds": last_age,
        }

    async def start(self) -> None:
        self._main_task = asyncio.create_task(self._run(), name="wss-run")
        self._watchdog_task = asyncio.create_task(self._watchdog(), name="wss-watchdog")

    async def _run(self) -> None:
        attempt = 0
        reconnect = False
        while not self._stopping:
            try:
                result = self._connect()
                self._conn = await result if asyncio.iscoroutine(result) else result
                attempt = 0
                self._connected = True
                self._connects_total += 1
                if reconnect:
                    self._reconnects_total += 1
                    log.info(
                        "wss reconnected (#%d), re-subscribing to %d assets",
                        self._reconnects_total, len(self._refs),
                    )
                    await self._sync_subscriptions()
                else:
                    log.info("wss connected, %d active subscriptions", len(self._refs))
                self._send_task = asyncio.create_task(self._send_loop(), name="wss-send")
                await self._recv_loop()
            except Exception:
                log.exception("wss run loop crashed")
            finally:
                self._connected = False
                if self._send_task is not None:
                    self._send_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await self._send_task
                    self._send_task = None
                if self._conn is not None:
                    with contextlib.suppress(Exception):
                        await self._conn.close()
                    self._conn = None

            if self._stopping:
                return
            reconnect = True
            attempt += 1
            backoff = _backoff_seconds(attempt)
            log.info("wss reconnecting in %.1fs (attempt %d)", backoff, attempt)
            await asyncio.sleep(backoff)

    async def stop(self) -> None:
        self._stopping = True
        if self._conn is not None:
            with contextlib.suppress(Exception):
                await self._conn.close()
        for t in (self._main_task, self._send_task, self._watchdog_task):
            if t is not None:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t

    async def subscribe(self, asset_id: str) -> None:
        prev = self._refs.get(asset_id, 0)
        self._refs[asset_id] = prev + 1
        log.info(
            "wss subscribe asset=%s ref=%d (total assets: %d)",
            asset_id[:16] + "...", prev + 1, len(self._refs),
        )
        if prev == 0:
            await self._sync_subscriptions()

    async def unsubscribe(self, asset_id: str) -> None:
        if asset_id not in self._refs:
            return
        self._refs[asset_id] -= 1
        new_ref = self._refs[asset_id]
        log.info(
            "wss unsubscribe asset=%s ref=%d", asset_id[:16] + "...", new_ref,
        )
        if new_ref <= 0:
            del self._refs[asset_id]
            await self._sync_subscriptions()

    async def _sync_subscriptions(self) -> None:
        """Push the FULL current asset set to the server.

        Polymarket's WSS treats `{"type": "market", "assets_ids": [...]}` as a
        SET-REPLACE — sending it again with a different list silently replaces
        the previous subscription rather than adding to it. Verified against
        wss-subscriptions-clob.polymarket.com on 2026-05-08: subscribing to A
        then subscribing to B produces only events for B.

        We therefore always send the complete asset list. When the set is empty
        we send nothing — there's no documented "clear all" message, but having
        zero subscriptions while connected is harmless (server stops pushing).
        """
        if not self._refs:
            return
        await self._send_queue.put(
            {"type": "market", "assets_ids": list(self._refs.keys())}
        )

    async def _send_loop(self) -> None:
        while not self._stopping:
            msg = await self._send_queue.get()
            try:
                assert self._conn is not None
                await self._conn.send(msg)
            except Exception:
                log.exception("wss send failed")

    async def _recv_loop(self) -> None:
        while not self._stopping:
            assert self._conn is not None
            msgs = await self._conn.recv()
            if isinstance(msgs, list):
                for m in msgs:
                    if isinstance(m, dict):
                        self._handle(m)
            elif isinstance(msgs, dict):
                self._handle(msgs)

    async def _watchdog(self) -> None:
        while not self._stopping:
            await asyncio.sleep(min(30.0, self._stale_timeout / 2))
            if self._refs and self._last_message_at is not None:
                elapsed = time.monotonic() - self._last_message_at
                if elapsed > self._stale_timeout:
                    log.warning(
                        "wss stale (%.0fs since last message), forcing reconnect", elapsed
                    )
                    if self._conn is not None:
                        with contextlib.suppress(Exception):
                            await self._conn.close()
                    self._last_message_at = None

    def _handle(self, msg: dict) -> None:
        self._last_message_at = time.monotonic()
        if msg.get("event_type") not in ("book", "price_change"):
            return
        asset_id = msg.get("asset_id") or msg.get("market")
        if not asset_id:
            return
        bid = _best_price(msg.get("bids", []), best="max")
        ask = _best_price(msg.get("asks", []), best="min")
        if bid is None or ask is None:
            return
        self._ticks_total += 1
        tick = PriceTick(asset_id=str(asset_id), bid=bid, ask=ask)
        if self.on_tick is not None:
            try:
                self.on_tick(tick)
            except Exception:
                log.exception("on_tick handler raised")


def _best_price(side: list[dict], *, best: str) -> float | None:
    prices = []
    for entry in side:
        try:
            prices.append(float(entry.get("price")))
        except (TypeError, ValueError):
            continue
    if not prices:
        return None
    return max(prices) if best == "max" else min(prices)


async def open_polymarket_connection(url: str) -> "PolymarketWebSocketConnection":
    ws = await websockets.connect(url, ping_interval=20, ping_timeout=20)
    return PolymarketWebSocketConnection(ws)


class PolymarketWebSocketConnection:
    def __init__(self, ws):
        self._ws = ws

    async def send(self, msg: dict) -> None:
        await self._ws.send(_json.dumps(msg))

    async def recv(self) -> dict | list:
        raw = await self._ws.recv()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError:
            return {}
        return data  # dict or list — caller flattens

    async def close(self) -> None:
        await self._ws.close()
