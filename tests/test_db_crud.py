import pytest

from polyalert.db import AlertLimitExceeded, Database


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    await d.connect()
    yield d
    await d.close()


async def test_upsert_user_is_idempotent(db):
    await db.upsert_user(42)
    await db.upsert_user(42)
    assert await db.user_exists(42)


async def test_create_alert_and_list(db):
    await db.upsert_user(42)
    a = await db.create_alert(
        user_id=42,
        market_slug="m",
        market_title="t",
        asset_id="tok1",
        outcome_label="Yes",
        side="mid",
        direction="above",
        threshold=0.55,
        max_per_user=10,
    )
    assert a.id > 0
    listed = await db.list_alerts(42)
    assert len(listed) == 1
    assert listed[0].id == a.id


async def test_create_alert_enforces_limit(db):
    await db.upsert_user(42)
    for _ in range(3):
        await db.create_alert(
            user_id=42, market_slug="m", market_title="t", asset_id="tok",
            outcome_label="Yes", side="mid", direction="above",
            threshold=0.5, max_per_user=3,
        )
    with pytest.raises(AlertLimitExceeded):
        await db.create_alert(
            user_id=42, market_slug="m", market_title="t", asset_id="tok",
            outcome_label="Yes", side="mid", direction="above",
            threshold=0.5, max_per_user=3,
        )


async def test_delete_alert_owned_by_user(db):
    await db.upsert_user(42)
    a = await db.create_alert(
        user_id=42, market_slug="m", market_title="t", asset_id="tok",
        outcome_label="Yes", side="mid", direction="above",
        threshold=0.5, max_per_user=10,
    )
    deleted = await db.delete_alert(alert_id=a.id, user_id=42)
    assert deleted is True
    assert await db.list_alerts(42) == []


async def test_delete_alert_other_user_returns_false(db):
    await db.upsert_user(42)
    await db.upsert_user(99)
    a = await db.create_alert(
        user_id=42, market_slug="m", market_title="t", asset_id="tok",
        outcome_label="Yes", side="mid", direction="above",
        threshold=0.5, max_per_user=10,
    )
    deleted = await db.delete_alert(alert_id=a.id, user_id=99)
    assert deleted is False


async def test_load_all_alerts(db):
    await db.upsert_user(42)
    await db.create_alert(
        user_id=42, market_slug="m", market_title="t", asset_id="tok-a",
        outcome_label="Yes", side="mid", direction="above",
        threshold=0.5, max_per_user=10,
    )
    await db.create_alert(
        user_id=42, market_slug="m", market_title="t", asset_id="tok-b",
        outcome_label="No", side="bid", direction="below",
        threshold=0.3, max_per_user=10,
    )
    all_alerts = await db.load_all_alerts()
    assert len(all_alerts) == 2


async def test_delete_user_cascades_alerts(db):
    await db.upsert_user(42)
    await db.create_alert(
        user_id=42, market_slug="m", market_title="t", asset_id="tok",
        outcome_label="Yes", side="mid", direction="above",
        threshold=0.5, max_per_user=10,
    )
    await db.delete_user(42)
    assert await db.list_alerts(42) == []
    assert not await db.user_exists(42)
