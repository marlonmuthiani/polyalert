import logging
from collections.abc import Awaitable, Callable

from aiogram.exceptions import TelegramForbiddenError

from polyalert.db import Database

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, *, bot, db: Database):
        self._bot = bot
        self._db = db
        # Optional callback invoked after a 403 user deletion so the engine
        # can purge its in-memory index.  Set as an attribute after construction.
        self.on_user_blocked: Callable[[int], Awaitable[None]] | None = None

    async def _handle_blocked(self, user_id: int) -> None:
        log.info("user %s blocked the bot, removing", user_id)
        await self._db.delete_user(user_id)
        if self.on_user_blocked is not None:
            await self.on_user_blocked(user_id)

    async def send(self, user_id: int, text: str) -> None:
        try:
            await self._bot.send_message(user_id, text)
            return
        except TelegramForbiddenError:
            await self._handle_blocked(user_id)
            return
        except Exception as e:
            log.warning("send to %s failed (1st): %s", user_id, e)

        # One retry
        try:
            await self._bot.send_message(user_id, text)
        except TelegramForbiddenError:
            await self._handle_blocked(user_id)
        except Exception as e:
            log.error("send to %s failed (2nd, dropping): %s", user_id, e)
