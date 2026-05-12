import aiosqlite

from polyalert.db import Database


async def test_migrations_create_expected_tables(tmp_path):
    path = tmp_path / "x.db"
    db = Database(str(path))
    await db.connect()
    try:
        async with aiosqlite.connect(str(path)) as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = {row[0] for row in await cursor.fetchall()}
        assert "users" in tables
        assert "alerts" in tables
        assert "schema_version" in tables
    finally:
        await db.close()


async def test_migrations_idempotent(tmp_path):
    path = tmp_path / "y.db"
    for _ in range(3):
        db = Database(str(path))
        await db.connect()
        await db.close()
    # If we got here without error, migrations are idempotent.
