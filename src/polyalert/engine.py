import asyncio
import contextlib
import logging
from typing import Protocol

from polyalert.db import Database
from polyalert.models import Alert, PriceTick, Side

log = logging.getLogger(__name__)


def current_price(side: Side, tick: PriceTick) -> float:
    if side == "bid":
        return tick.bid
    if side == "ask":
        return tick.ask
    return tick.mid


def should_fire(alert: Alert, tick: PriceTick) -> bool:
    if alert.asset_id != tick.asset_id:
        return False
    price = current_price(alert.side, tick)
    if alert.direction == "above":
        return price >= alert.threshold
    return price <= alert.threshold


class Notifier(Protocol):
    async def send(self, user_id: int, text: str) -> None: ...


class WSS(Protocol):
    async def subscribe(self, asset_id: str) -> None: ...
    async def unsubscribe(self, asset_id: str) -> None: ...


class AlertEngine:
    def __init__(self, *, db: Database, notifier: Notifier, wss: WSS):
        self._db = db
        self._notifier = notifier
        self._wss = wss
        self._index: dict[str, dict[int, Alert]] = {}  # asset_id -> {alert_id: Alert}
        self._latest_ticks: dict[str, PriceTick] = {}  # asset_id -> last seen tick
        self._tick_queue: asyncio.Queue[PriceTick] = asyncio.Queue()
        self._consumer_task: asyncio.Task | None = None
        self._fired_total = 0

    def stats(self) -> dict:
        return {
            "indexed_alerts": sum(len(b) for b in self._index.values()),
            "tracked_assets": len(self._index),
            "fired_total": self._fired_total,
            "queue_size": self._tick_queue.qsize(),
        }

    def get_latest_tick(self, asset_id: str) -> PriceTick | None:
        """Return the last PriceTick observed for `asset_id` from WSS, or None
        if we haven't seen one yet (e.g. just-subscribed, illiquid market)."""
        return self._latest_ticks.get(asset_id)

    async def start(self) -> None:
        existing = await self._db.load_all_alerts()
        for a in existing:
            self._index.setdefault(a.asset_id, {})[a.id] = a
        for asset_id in self._index:
            await self._wss.subscribe(asset_id)
        self._consumer_task = asyncio.create_task(
            self._consume_ticks(), name="alert-engine-consumer"
        )

    async def stop(self) -> None:
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._consumer_task

    async def register(self, alert: Alert) -> None:
        already_subscribed = alert.asset_id in self._index
        self._index.setdefault(alert.asset_id, {})[alert.id] = alert
        if not already_subscribed:
            await self._wss.subscribe(alert.asset_id)

    async def unregister(self, alert_id: int, *, user_id: int) -> bool:
        deleted = await self._db.delete_alert(alert_id=alert_id, user_id=user_id)
        if not deleted:
            return False
        await self._remove_from_index(alert_id)
        return True

    def submit_tick(self, tick: PriceTick) -> None:
        """Enqueue a tick for serialised processing (safe to call from a sync callback)."""
        self._tick_queue.put_nowait(tick)

    async def _consume_ticks(self) -> None:
        while True:
            tick = await self._tick_queue.get()
            try:
                await self.handle_tick(tick)
            except Exception:
                log.exception("error processing tick")

    async def purge_user(self, user_id: int) -> None:
        """Remove all alerts for a user from the in-memory index and unsubscribe orphaned assets."""
        to_remove: list[int] = []
        for bucket in self._index.values():
            for alert_id, alert in bucket.items():
                if alert.user_id == user_id:
                    to_remove.append(alert_id)
        for alert_id in to_remove:
            await self._remove_from_index(alert_id)

    async def handle_tick(self, tick: PriceTick) -> None:
        # Cache the freshest tick per asset for /list and other read paths.
        # Stored even if no alert currently matches — the WSS may be pushing
        # events for an asset right after register() but before bucket lookup.
        self._latest_ticks[tick.asset_id] = tick
        bucket = self._index.get(tick.asset_id)
        if not bucket:
            return
        fired_ids: list[int] = []
        for alert_id, alert in list(bucket.items()):
            if should_fire(alert, tick):
                fired_ids.append(alert_id)
                price = current_price(alert.side, tick)
                text = self._format_fired(alert, price)
                try:
                    await self._notifier.send(alert.user_id, text)
                except Exception:
                    log.exception("notifier failed for alert %s", alert_id)
        for alert_id in fired_ids:
            await self._db.delete_alert_by_id(alert_id)
            await self._remove_from_index(alert_id)
            self._fired_total += 1

    async def _remove_from_index(self, alert_id: int) -> None:
        for asset_id, bucket in list(self._index.items()):
            if alert_id in bucket:
                del bucket[alert_id]
                if not bucket:
                    del self._index[asset_id]
                    self._latest_ticks.pop(asset_id, None)
                    await self._wss.unsubscribe(asset_id)
                return

    @staticmethod
    def _format_fired(alert: Alert, price: float) -> str:
        arrow = "↑" if alert.direction == "above" else "↓"
        return (
            f"🔔 {alert.market_title}\n"
            f"{alert.outcome_label} · {alert.side} = {price:.4f}\n"
            f"(threshold: {alert.threshold:g} {arrow})"
        )
