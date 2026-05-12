from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramForbiddenError

from polyalert.db import Database
from polyalert.notifier import TelegramNotifier


class FakeBot:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = 0

    async def send_message(self, chat_id, text):
        self.calls += 1
        result = self.behavior(self.calls)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "n.db"))
    await d.connect()
    yield d
    await d.close()


async def test_send_succeeds(db):
    bot = FakeBot(lambda n: None)
    notifier = TelegramNotifier(bot=bot, db=db)
    await notifier.send(42, "hi")
    assert bot.calls == 1


async def test_send_retries_once_on_failure(db):
    def behavior(call_n):
        if call_n == 1:
            return RuntimeError("boom")
        return None
    bot = FakeBot(behavior)
    notifier = TelegramNotifier(bot=bot, db=db)
    await notifier.send(42, "hi")
    assert bot.calls == 2


async def test_send_drops_after_two_failures(db):
    bot = FakeBot(lambda n: RuntimeError("boom"))
    notifier = TelegramNotifier(bot=bot, db=db)
    await notifier.send(42, "hi")  # should not raise
    assert bot.calls == 2


async def test_403_deletes_user_and_alerts(db):
    await db.upsert_user(42)
    await db.create_alert(
        user_id=42, market_slug="m", market_title="t", asset_id="tok",
        outcome_label="Yes", side="mid", direction="above",
        threshold=0.5, max_per_user=10,
    )
    bot = FakeBot(lambda n: TelegramForbiddenError(method=AsyncMock(), message="blocked"))
    notifier = TelegramNotifier(bot=bot, db=db)
    await notifier.send(42, "hi")
    assert not await db.user_exists(42)
    assert await db.list_alerts(42) == []


async def test_403_calls_on_user_blocked_callback(db):
    called: list[int] = []

    async def on_blocked(uid: int) -> None:
        called.append(uid)

    bot = FakeBot(lambda n: TelegramForbiddenError(method=AsyncMock(), message="blocked"))
    notifier = TelegramNotifier(bot=bot, db=db)
    notifier.on_user_blocked = on_blocked
    await notifier.send(42, "hi")
    assert called == [42]
