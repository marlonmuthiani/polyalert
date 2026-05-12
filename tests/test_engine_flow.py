import asyncio

import pytest

from polyalert.db import Database
from polyalert.engine import AlertEngine
from polyalert.models import PriceTick


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send(self, user_id: int, text: str) -> None:
        self.sent.append((user_id, text))


class FakeWSS:
    def __init__(self):
        self.subs: list[str] = []
        self.unsubs: list[str] = []

    async def subscribe(self, asset_id: str) -> None:
        self.subs.append(asset_id)

    async def unsubscribe(self, asset_id: str) -> None:
        self.unsubs.append(asset_id)


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "engine.db"))
    await d.connect()
    yield d
    await d.close()


async def test_engine_loads_existing_alerts_on_start(db):
    await db.upsert_user(1)
    await db.create_alert(
        user_id=1, market_slug="m", market_title="T", asset_id="tok",
        outcome_label="Yes", side="mid", direction="above",
        threshold=0.5, max_per_user=10,
    )
    wss = FakeWSS()
    engine = AlertEngine(db=db, notifier=FakeNotifier(), wss=wss)
    await engine.start()
    assert wss.subs == ["tok"]


async def test_register_alert_subscribes(db):
    await db.upsert_user(1)
    wss = FakeWSS()
    engine = AlertEngine(db=db, notifier=FakeNotifier(), wss=wss)
    await engine.start()
    a = await db.create_alert(
        user_id=1, market_slug="m", market_title="T", asset_id="tok",
        outcome_label="Yes", side="mid", direction="above",
        threshold=0.5, max_per_user=10,
    )
    await engine.register(a)
    assert "tok" in wss.subs


async def test_tick_fires_matching_alert_and_removes_it(db):
    await db.upsert_user(1)
    wss = FakeWSS()
    notifier = FakeNotifier()
    engine = AlertEngine(db=db, notifier=notifier, wss=wss)
    await engine.start()
    a = await db.create_alert(
        user_id=1, market_slug="m", market_title="Will it?", asset_id="tok",
        outcome_label="Yes", side="mid", direction="above",
        threshold=0.5, max_per_user=10,
    )
    await engine.register(a)

    await engine.handle_tick(PriceTick("tok", bid=0.55, ask=0.57))

    assert len(notifier.sent) == 1
    user_id, text = notifier.sent[0]
    assert user_id == 1
    assert "Will it?" in text
    assert "0.5" in text
    # Alert removed from DB
    assert await db.list_alerts(1) == []
    # Unsubscribed
    assert "tok" in wss.unsubs


async def test_tick_does_not_fire_non_matching(db):
    await db.upsert_user(1)
    wss = FakeWSS()
    notifier = FakeNotifier()
    engine = AlertEngine(db=db, notifier=notifier, wss=wss)
    await engine.start()
    a = await db.create_alert(
        user_id=1, market_slug="m", market_title="T", asset_id="tok",
        outcome_label="Yes", side="mid", direction="above",
        threshold=0.5, max_per_user=10,
    )
    await engine.register(a)
    await engine.handle_tick(PriceTick("tok", bid=0.40, ask=0.42))
    assert notifier.sent == []
    assert len(await db.list_alerts(1)) == 1


async def test_unregister_unsubscribes_when_last(db):
    await db.upsert_user(1)
    wss = FakeWSS()
    engine = AlertEngine(db=db, notifier=FakeNotifier(), wss=wss)
    await engine.start()
    a = await db.create_alert(
        user_id=1, market_slug="m", market_title="T", asset_id="tok",
        outcome_label="Yes", side="mid", direction="above",
        threshold=0.5, max_per_user=10,
    )
    await engine.register(a)
    await engine.unregister(a.id, user_id=1)
    assert "tok" in wss.unsubs
    assert await db.list_alerts(1) == []


async def test_purge_user_removes_all_alerts_and_unsubscribes(db):
    await db.upsert_user(1)
    wss = FakeWSS()
    engine = AlertEngine(db=db, notifier=FakeNotifier(), wss=wss)
    await engine.start()
    a1 = await db.create_alert(
        user_id=1, market_slug="m", market_title="T", asset_id="tok-A",
        outcome_label="Yes", side="mid", direction="above",
        threshold=0.5, max_per_user=10,
    )
    a2 = await db.create_alert(
        user_id=1, market_slug="m", market_title="T", asset_id="tok-B",
        outcome_label="No", side="bid", direction="below",
        threshold=0.4, max_per_user=10,
    )
    await engine.register(a1)
    await engine.register(a2)
    # Simulate db.delete_user already cascaded; only purge index
    await engine.purge_user(1)
    assert "tok-A" in wss.unsubs
    assert "tok-B" in wss.unsubs
    await engine.stop()


async def test_submit_tick_processes_via_queue(db):
    await db.upsert_user(1)
    wss = FakeWSS()
    notifier = FakeNotifier()
    engine = AlertEngine(db=db, notifier=notifier, wss=wss)
    await engine.start()
    a = await db.create_alert(
        user_id=1, market_slug="m", market_title="T", asset_id="tok",
        outcome_label="Yes", side="mid", direction="above",
        threshold=0.5, max_per_user=10,
    )
    await engine.register(a)

    engine.submit_tick(PriceTick("tok", bid=0.55, ask=0.57))
    # Give consumer a chance to run
    await asyncio.sleep(0.05)
    assert len(notifier.sent) == 1
    await engine.stop()
