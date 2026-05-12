import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher

from polyalert.bot import handlers
from polyalert.config import Settings
from polyalert.db import Database
from polyalert.engine import AlertEngine
from polyalert.notifier import TelegramNotifier
from polyalert.polymarket.rest import PolymarketRest
from polyalert.polymarket.wss import WSSManager, open_polymarket_connection

log = logging.getLogger("polyalert")


async def amain() -> None:
    settings = Settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    db = Database(settings.db_path)
    await db.connect()

    rest = PolymarketRest(
        settings.polymarket_rest_url,
        clob_url=settings.polymarket_clob_url,
    )
    bot = Bot(token=settings.telegram_bot_token)
    notifier = TelegramNotifier(bot=bot, db=db)

    wss = WSSManager(
        connect=lambda: open_polymarket_connection(settings.polymarket_wss_url),
        stale_timeout=settings.wss_stale_timeout_seconds,
    )
    engine = AlertEngine(db=db, notifier=notifier, wss=wss)
    # Late-bind purge callback so the engine cleans its index when a user blocks the bot.
    notifier.on_user_blocked = engine.purge_user
    wss.on_tick = engine.submit_tick

    handlers.wire(db=db, engine=engine, rest=rest, settings=settings, wss=wss)

    dp = Dispatcher()
    dp.include_router(handlers.router)

    await wss.start()
    await engine.start()
    log.info("polyalert started")
    try:
        await dp.start_polling(bot)
    finally:
        log.info("shutting down")
        await engine.stop()
        await wss.stop()
        await rest.close()
        await bot.session.close()
        await db.close()


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(amain())


if __name__ == "__main__":
    main()
