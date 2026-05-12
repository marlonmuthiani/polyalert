import importlib.resources
from datetime import UTC, datetime

import aiosqlite

from polyalert.models import Alert


class AlertLimitExceeded(Exception):
    pass


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = aiosqlite.Row
        await self._run_migrations()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "Database not connected"
        return self._conn

    async def _run_migrations(self) -> None:
        await self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
        )
        cursor = await self.conn.execute("SELECT MAX(version) FROM schema_version")
        row = await cursor.fetchone()
        current = row[0] if row and row[0] is not None else 0

        files = importlib.resources.files("polyalert.migrations")
        migrations = sorted(
            (p for p in files.iterdir() if p.name.endswith(".sql")),
            key=lambda p: p.name,
        )
        for path in migrations:
            version = int(path.name.split("_", 1)[0])
            if version <= current:
                continue
            sql = path.read_text()
            await self.conn.executescript(sql)
            await self.conn.execute(
                "INSERT INTO schema_version(version) VALUES (?)", (version,)
            )
            await self.conn.commit()

    async def upsert_user(self, telegram_id: int) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO users(telegram_id, created_at) VALUES (?, ?)",
            (telegram_id, datetime.now(UTC).isoformat()),
        )
        await self.conn.commit()

    async def user_exists(self, telegram_id: int) -> bool:
        cursor = await self.conn.execute(
            "SELECT 1 FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        return await cursor.fetchone() is not None

    async def delete_user(self, telegram_id: int) -> None:
        await self.conn.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
        await self.conn.commit()

    async def count_alerts(self, user_id: int) -> int:
        cursor = await self.conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def create_alert(
        self,
        *,
        user_id: int,
        market_slug: str,
        market_title: str,
        asset_id: str,
        outcome_label: str,
        side: str,
        direction: str,
        threshold: float,
        max_per_user: int,
    ) -> Alert:
        existing = await self.count_alerts(user_id)
        if existing >= max_per_user:
            raise AlertLimitExceeded(f"limit {max_per_user} reached")
        created_at = datetime.now(UTC).isoformat()
        cursor = await self.conn.execute(
            """
            INSERT INTO alerts(user_id, market_slug, market_title, asset_id,
                               outcome_label, side, direction, threshold, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, market_slug, market_title, asset_id,
                outcome_label, side, direction, threshold, created_at,
            ),
        )
        await self.conn.commit()
        return Alert(
            id=cursor.lastrowid or 0,
            user_id=user_id,
            market_slug=market_slug,
            market_title=market_title,
            asset_id=asset_id,
            outcome_label=outcome_label,
            side=side,  # type: ignore[arg-type]
            direction=direction,  # type: ignore[arg-type]
            threshold=threshold,
            created_at=created_at,
        )

    async def list_alerts(self, user_id: int) -> list[Alert]:
        cursor = await self.conn.execute(
            "SELECT * FROM alerts WHERE user_id = ? ORDER BY id", (user_id,)
        )
        return [self._row_to_alert(r) for r in await cursor.fetchall()]

    async def load_all_alerts(self) -> list[Alert]:
        cursor = await self.conn.execute("SELECT * FROM alerts ORDER BY id")
        return [self._row_to_alert(r) for r in await cursor.fetchall()]

    async def delete_alert(self, *, alert_id: int, user_id: int) -> bool:
        cursor = await self.conn.execute(
            "DELETE FROM alerts WHERE id = ? AND user_id = ?", (alert_id, user_id)
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def delete_alert_by_id(self, alert_id: int) -> None:
        await self.conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        await self.conn.commit()

    @staticmethod
    def _row_to_alert(row) -> Alert:
        return Alert(
            id=row["id"],
            user_id=row["user_id"],
            market_slug=row["market_slug"],
            market_title=row["market_title"],
            asset_id=row["asset_id"],
            outcome_label=row["outcome_label"],
            side=row["side"],
            direction=row["direction"],
            threshold=row["threshold"],
            created_at=row["created_at"],
        )
