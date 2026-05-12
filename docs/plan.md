# PolyAlert Implementation Plan

**Goal:** Build a public Telegram bot that sends notifications when prices on Polymarket markets cross user-defined thresholds.

**Architecture:** Single Python asyncio process. Three logical layers (Telegram bot via aiogram 3.x, Alert engine, Polymarket REST + WSS client) sharing a SQLite database. Single shared WSS connection with ref-counted subscriptions per market token.

**Tech Stack:** Python 3.12, aiogram 3.x, aiosqlite, httpx, websockets, pydantic-settings, pytest, pytest-asyncio, pytest-httpx, ruff.

**Reference spec:** [`docs/design.md`](design.md)

---

## Phase 0: Bootstrap

### Task 1: Project skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/polyalert/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.env.example`
- Create: `README.md`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "polyalert"
version = "0.1.0"
description = "Telegram bot for Polymarket price alerts"
requires-python = ">=3.12"
dependencies = [
    "aiogram>=3.13,<4",
    "aiosqlite>=0.20",
    "httpx>=0.27",
    "websockets>=13",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "structlog>=24.4",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-httpx>=0.32",
    "ruff>=0.7",
]

[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]
```

- [ ] **Step 2: Create empty `src/polyalert/__init__.py` and `tests/__init__.py`**

```python
# src/polyalert/__init__.py
__version__ = "0.1.0"
```

```python
# tests/__init__.py
```

- [ ] **Step 3: Create `tests/conftest.py`**

```python
import asyncio
import pytest


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()
```

- [ ] **Step 4: Create `.env.example`**

```env
# Telegram bot token from @BotFather
TELEGRAM_BOT_TOKEN=

# Polymarket APIs (defaults usually fine)
POLYMARKET_REST_URL=https://gamma-api.polymarket.com
POLYMARKET_WSS_URL=wss://ws-subscriptions-clob.polymarket.com/ws/market

# Storage
DB_PATH=./polyalert.db

# Limits & timeouts
MAX_ALERTS_PER_USER=10
WSS_STALE_TIMEOUT_SECONDS=300

# Logging
LOG_LEVEL=INFO
```

- [ ] **Step 5: Minimal `README.md`**

```markdown
# PolyAlert

Telegram bot for Polymarket price alerts. See `docs/design.md` for full design.

## Quick start (dev)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill TELEGRAM_BOT_TOKEN
python -m polyalert
```

## Tests

```bash
pytest
```
```

- [ ] **Step 6: Install deps and verify import**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -c "import polyalert; print(polyalert.__version__)"
```

Expected output: `0.1.0`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/ tests/ .env.example README.md
git commit -m "feat: project skeleton with pyproject and dev deps"
```

---

## Phase 1: Pure-logic foundation

### Task 2: Domain models

**Files:**
- Create: `src/polyalert/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from polyalert.models import Alert, Market, Outcome, PriceTick


def test_pricetick_mid_is_average_of_bid_ask():
    tick = PriceTick(asset_id="t1", bid=0.4, ask=0.5)
    assert tick.mid == 0.45


def test_alert_describes_self_human_readable():
    alert = Alert(
        id=1,
        user_id=42,
        market_slug="x",
        market_title="Will it snow?",
        asset_id="tok1",
        outcome_label="Yes",
        side="mid",
        direction="above",
        threshold=0.55,
        created_at="2026-05-08T10:00:00Z",
    )
    assert "Will it snow?" in alert.describe()
    assert "Yes" in alert.describe()
    assert "0.55" in alert.describe()


def test_market_finds_token_for_outcome():
    market = Market(
        slug="m",
        title="t",
        outcomes=[
            Outcome(label="Yes", token_id="tok-yes"),
            Outcome(label="No", token_id="tok-no"),
        ],
        closed=False,
    )
    assert market.token_for("Yes") == "tok-yes"
    assert market.token_for("No") == "tok-no"
```

- [ ] **Step 2: Run, expect import error**

`pytest tests/test_models.py -v` → FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write `src/polyalert/models.py`**

```python
from dataclasses import dataclass
from typing import Literal

Side = Literal["bid", "ask", "mid"]
Direction = Literal["above", "below"]


@dataclass(frozen=True)
class PriceTick:
    asset_id: str
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class Outcome:
    label: str
    token_id: str


@dataclass(frozen=True)
class Market:
    slug: str
    title: str
    outcomes: list[Outcome]
    closed: bool

    def token_for(self, label: str) -> str | None:
        for o in self.outcomes:
            if o.label == label:
                return o.token_id
        return None


@dataclass(frozen=True)
class Event:
    slug: str
    title: str
    markets: list[Market]


@dataclass(frozen=True)
class Alert:
    id: int
    user_id: int
    market_slug: str
    market_title: str
    asset_id: str
    outcome_label: str
    side: Side
    direction: Direction
    threshold: float
    created_at: str

    def describe(self) -> str:
        arrow = "↑" if self.direction == "above" else "↓"
        return (
            f"#{self.id} · {self.market_title} · {self.outcome_label} · "
            f"{self.side} {arrow} {self.threshold:g}"
        )
```

- [ ] **Step 4: Run tests**

`pytest tests/test_models.py -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polyalert/models.py tests/test_models.py
git commit -m "feat: domain models (Alert, Market, Outcome, PriceTick, Event)"
```

---

### Task 3: Config

**Files:**
- Create: `src/polyalert/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest
from polyalert.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc:def")
    monkeypatch.setenv("DB_PATH", "/tmp/x.db")
    s = Settings()
    assert s.telegram_bot_token == "abc:def"
    assert s.db_path == "/tmp/x.db"
    assert s.max_alerts_per_user == 10  # default
    assert s.polymarket_rest_url.startswith("https://")
    assert s.polymarket_wss_url.startswith("wss://")


def test_settings_requires_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(Exception):
        Settings(_env_file=None)
```

- [ ] **Step 2: Run, expect import error**

`pytest tests/test_config.py -v` → FAIL.

- [ ] **Step 3: Write `src/polyalert/config.py`**

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(..., min_length=10)
    polymarket_rest_url: str = "https://gamma-api.polymarket.com"
    polymarket_wss_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    db_path: str = "./polyalert.db"
    max_alerts_per_user: int = 10
    wss_stale_timeout_seconds: int = 300
    log_level: str = "INFO"
```

- [ ] **Step 4: Run tests**

`pytest tests/test_config.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polyalert/config.py tests/test_config.py
git commit -m "feat: settings loaded from .env via pydantic-settings"
```

---

### Task 4: URL parser

**Files:**
- Create: `src/polyalert/polymarket/__init__.py`
- Create: `src/polyalert/polymarket/url.py`
- Create: `tests/test_url.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_url.py
import pytest
from polyalert.polymarket.url import InvalidURL, parse_polymarket_url


def test_event_with_market():
    e, m = parse_polymarket_url(
        "https://polymarket.com/event/will-the-us-confirm-that-aliens-exist-before-2027"
        "/will-the-us-confirm-that-aliens-exist-by-may-31"
    )
    assert e == "will-the-us-confirm-that-aliens-exist-before-2027"
    assert m == "will-the-us-confirm-that-aliens-exist-by-may-31"


def test_event_only():
    e, m = parse_polymarket_url("https://polymarket.com/event/some-event")
    assert e == "some-event"
    assert m is None


def test_market_path():
    e, m = parse_polymarket_url("https://polymarket.com/market/some-market")
    assert e is None
    assert m == "some-market"


def test_strips_query_and_fragment():
    e, m = parse_polymarket_url("https://polymarket.com/event/x/y?ref=tg#anchor")
    assert e == "x"
    assert m == "y"


def test_accepts_http_and_no_scheme():
    e, m = parse_polymarket_url("polymarket.com/event/x")
    assert e == "x"


@pytest.mark.parametrize("bad", [
    "",
    "not a url",
    "https://example.com/event/x",
    "https://polymarket.com/",
    "https://polymarket.com/profile/foo",
])
def test_invalid_url_raises(bad):
    with pytest.raises(InvalidURL):
        parse_polymarket_url(bad)
```

- [ ] **Step 2: Run, expect import error**

`pytest tests/test_url.py -v` → FAIL.

- [ ] **Step 3: Write `src/polyalert/polymarket/__init__.py` (empty)**

```python
# src/polyalert/polymarket/__init__.py
```

- [ ] **Step 4: Write `src/polyalert/polymarket/url.py`**

```python
from urllib.parse import urlparse


class InvalidURL(ValueError):
    pass


def parse_polymarket_url(raw: str) -> tuple[str | None, str | None]:
    """Parse Polymarket URL. Returns (event_slug, market_slug). At least one is non-None.

    Supported shapes:
      polymarket.com/event/<event-slug>
      polymarket.com/event/<event-slug>/<market-slug>
      polymarket.com/market/<market-slug>
    """
    if not raw or not isinstance(raw, str):
        raise InvalidURL("empty input")

    text = raw.strip()
    if "://" not in text:
        text = "https://" + text

    parsed = urlparse(text)
    host = (parsed.netloc or "").lower()
    if not host.endswith("polymarket.com"):
        raise InvalidURL(f"not a polymarket host: {host!r}")

    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        raise InvalidURL("no path")

    if parts[0] == "event":
        if len(parts) == 2:
            return parts[1], None
        if len(parts) >= 3:
            return parts[1], parts[2]
        raise InvalidURL("event without slug")

    if parts[0] == "market":
        if len(parts) >= 2:
            return None, parts[1]
        raise InvalidURL("market without slug")

    raise InvalidURL(f"unsupported path: /{parts[0]}")
```

- [ ] **Step 5: Run tests**

`pytest tests/test_url.py -v` → PASS.

- [ ] **Step 6: Commit**

```bash
git add src/polyalert/polymarket/__init__.py src/polyalert/polymarket/url.py tests/test_url.py
git commit -m "feat: parse polymarket URLs into (event_slug, market_slug)"
```

---

## Phase 2: Storage

### Task 5: Database schema and migrations

**Files:**
- Create: `src/polyalert/migrations/__init__.py`
- Create: `src/polyalert/migrations/001_init.sql`
- Create: `src/polyalert/db.py`
- Create: `tests/test_db_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_schema.py
import aiosqlite
import pytest
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
```

- [ ] **Step 2: Run, expect import error**

`pytest tests/test_db_schema.py -v` → FAIL.

- [ ] **Step 3: Create `src/polyalert/migrations/__init__.py` (empty)**

```python
# src/polyalert/migrations/__init__.py
```

- [ ] **Step 4: Create `src/polyalert/migrations/001_init.sql`**

```sql
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    market_slug   TEXT NOT NULL,
    market_title  TEXT NOT NULL,
    asset_id      TEXT NOT NULL,
    outcome_label TEXT NOT NULL,
    side          TEXT NOT NULL CHECK (side IN ('bid','ask','mid')),
    direction     TEXT NOT NULL CHECK (direction IN ('above','below')),
    threshold     REAL NOT NULL CHECK (threshold > 0 AND threshold < 1),
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_asset_id ON alerts(asset_id);
CREATE INDEX IF NOT EXISTS idx_alerts_user_id  ON alerts(user_id);
```

- [ ] **Step 5: Write `src/polyalert/db.py` (just connect + migrations for now)**

```python
import importlib.resources
import aiosqlite


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
```

- [ ] **Step 6: Update `pyproject.toml` to include migration .sql files**

Add under `[tool.setuptools]`:

```toml
[tool.setuptools.package-data]
"polyalert.migrations" = ["*.sql"]
```

- [ ] **Step 7: Run tests**

`pytest tests/test_db_schema.py -v` → PASS.

- [ ] **Step 8: Commit**

```bash
git add src/polyalert/migrations/ src/polyalert/db.py tests/test_db_schema.py pyproject.toml
git commit -m "feat: sqlite db with migrations runner and initial schema"
```

---

### Task 6: Database CRUD

**Files:**
- Modify: `src/polyalert/db.py`
- Create: `tests/test_db_crud.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db_crud.py
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
```

- [ ] **Step 2: Run tests, expect failures**

`pytest tests/test_db_crud.py -v` → FAIL (methods missing).

- [ ] **Step 3: Append CRUD methods to `src/polyalert/db.py`**

Add at the top of the file after imports:

```python
from datetime import datetime, timezone

from polyalert.models import Alert


class AlertLimitExceeded(Exception):
    pass
```

Add inside the `Database` class (after `_run_migrations`):

```python
    async def upsert_user(self, telegram_id: int) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO users(telegram_id, created_at) VALUES (?, ?)",
            (telegram_id, datetime.now(timezone.utc).isoformat()),
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
        created_at = datetime.now(timezone.utc).isoformat()
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
```

- [ ] **Step 4: Run tests**

`pytest tests/test_db_crud.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polyalert/db.py tests/test_db_crud.py
git commit -m "feat: db CRUD for users and alerts with per-user limit"
```

---

## Phase 3: External APIs

### Task 7: Polymarket REST client

**Files:**
- Create: `src/polyalert/polymarket/rest.py`
- Create: `tests/test_polymarket_rest.py`

- [ ] **Step 1: Inspect real API response**

Run these and read the JSON. The exact field names matter:

```bash
curl -s "https://gamma-api.polymarket.com/markets?slug=will-the-us-confirm-that-aliens-exist-by-may-31" | python -m json.tool | head -80
curl -s "https://gamma-api.polymarket.com/events?slug=will-the-us-confirm-that-aliens-exist-before-2027" | python -m json.tool | head -120
```

Confirm field names: `slug`, `question`, `outcomes` (JSON-encoded list string), `clobTokenIds` (JSON-encoded list string), `closed`, `active`, `markets` (on event).

If any field name differs from what's used below, adjust the parsing accordingly. **Do not skip this step** — Polymarket changes shapes occasionally.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_polymarket_rest.py
import json

import pytest
from polyalert.polymarket.rest import MarketNotFound, PolymarketRest


def _market_payload(slug="m1", title="Q?", closed=False, active=True):
    return {
        "slug": slug,
        "question": title,
        "outcomes": json.dumps(["Yes", "No"]),
        "clobTokenIds": json.dumps(["tok-yes", "tok-no"]),
        "closed": closed,
        "active": active,
    }


async def test_get_market_by_slug(httpx_mock):
    httpx_mock.add_response(
        url="https://gamma-api.polymarket.com/markets?slug=foo",
        json=[_market_payload(slug="foo", title="Will it rain?")],
    )
    client = PolymarketRest("https://gamma-api.polymarket.com")
    m = await client.get_market("foo")
    await client.close()
    assert m.slug == "foo"
    assert m.title == "Will it rain?"
    assert [o.label for o in m.outcomes] == ["Yes", "No"]
    assert [o.token_id for o in m.outcomes] == ["tok-yes", "tok-no"]
    assert m.closed is False


async def test_get_market_not_found(httpx_mock):
    httpx_mock.add_response(
        url="https://gamma-api.polymarket.com/markets?slug=nope",
        json=[],
    )
    client = PolymarketRest("https://gamma-api.polymarket.com")
    with pytest.raises(MarketNotFound):
        await client.get_market("nope")
    await client.close()


async def test_get_event_with_markets(httpx_mock):
    httpx_mock.add_response(
        url="https://gamma-api.polymarket.com/events?slug=ev",
        json=[{
            "slug": "ev",
            "title": "Event",
            "markets": [
                _market_payload(slug="m-a", title="A?"),
                _market_payload(slug="m-b", title="B?", closed=True),
            ],
        }],
    )
    client = PolymarketRest("https://gamma-api.polymarket.com")
    e = await client.get_event("ev")
    await client.close()
    assert e.slug == "ev"
    assert [m.slug for m in e.markets] == ["m-a", "m-b"]
    assert e.markets[1].closed is True


async def test_market_treats_inactive_as_closed(httpx_mock):
    httpx_mock.add_response(
        url="https://gamma-api.polymarket.com/markets?slug=x",
        json=[_market_payload(slug="x", active=False)],
    )
    client = PolymarketRest("https://gamma-api.polymarket.com")
    m = await client.get_market("x")
    await client.close()
    assert m.closed is True
```

- [ ] **Step 3: Run, expect import error**

`pytest tests/test_polymarket_rest.py -v` → FAIL.

- [ ] **Step 4: Write `src/polyalert/polymarket/rest.py`**

```python
import json
from typing import Any

import httpx

from polyalert.models import Event, Market, Outcome


class MarketNotFound(Exception):
    pass


class EventNotFound(Exception):
    pass


class PolymarketRest:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get_market(self, slug: str) -> Market:
        resp = await self._client.get("/markets", params={"slug": slug})
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise MarketNotFound(slug)
        return self._parse_market(data[0])

    async def get_event(self, slug: str) -> Event:
        resp = await self._client.get("/events", params={"slug": slug})
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise EventNotFound(slug)
        item = data[0]
        markets = [self._parse_market(m) for m in item.get("markets", [])]
        return Event(
            slug=item.get("slug", slug),
            title=item.get("title", ""),
            markets=markets,
        )

    @staticmethod
    def _parse_market(item: dict[str, Any]) -> Market:
        labels = _maybe_json_list(item.get("outcomes"))
        token_ids = _maybe_json_list(item.get("clobTokenIds"))
        outcomes = [
            Outcome(label=str(label), token_id=str(tid))
            for label, tid in zip(labels, token_ids, strict=False)
        ]
        closed = bool(item.get("closed")) or not bool(item.get("active", True))
        return Market(
            slug=str(item.get("slug", "")),
            title=str(item.get("question") or item.get("title", "")),
            outcomes=outcomes,
            closed=closed,
        )


def _maybe_json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []
```

- [ ] **Step 5: Run tests**

`pytest tests/test_polymarket_rest.py -v` → PASS.

- [ ] **Step 6: Commit**

```bash
git add src/polyalert/polymarket/rest.py tests/test_polymarket_rest.py
git commit -m "feat: gamma-api client for markets and events"
```

---

### Task 8: WSS Manager — connection abstraction

**Files:**
- Create: `src/polyalert/polymarket/wss.py`
- Create: `tests/test_wss_manager.py`

The manager talks to a `Connection` interface, so we test against a fake. Reconnect/staleness happens at the manager level, not the connection level.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_wss_manager.py
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


def test_unsubscribe_only_when_refcount_zero():
    async def run():
        conn = FakeConn()
        mgr = WSSManager(connect=lambda: conn)
        await mgr.start()
        await mgr.subscribe("tok1")
        await mgr.subscribe("tok1")
        await mgr.unsubscribe("tok1")
        await asyncio.sleep(0)
        # Still one ref → no unsubscribe
        assert not any(m.get("type") == "unsubscribe" for m in conn.sent)
        await mgr.unsubscribe("tok1")
        await asyncio.sleep(0); await asyncio.sleep(0)
        assert any(
            m.get("type") == "unsubscribe" and "tok1" in m.get("assets_ids", [])
            for m in conn.sent
        )
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
```

- [ ] **Step 2: Run, expect import error**

`pytest tests/test_wss_manager.py -v` → FAIL.

- [ ] **Step 3: Write `src/polyalert/polymarket/wss.py`**

```python
import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from polyalert.models import PriceTick

log = logging.getLogger(__name__)

OnTick = Callable[[PriceTick], None]
ConnectFn = Callable[[], Awaitable["WSSConnection"] | "WSSConnection"]


class WSSConnection(Protocol):
    async def send(self, msg: dict) -> None: ...
    async def recv(self) -> dict: ...
    async def close(self) -> None: ...


class WSSManager:
    """Maintains a single Polymarket WSS connection with ref-counted subscriptions.

    Reconnection and staleness handling are added in Task 9.
    """

    def __init__(self, connect: ConnectFn):
        self._connect = connect
        self._conn: WSSConnection | None = None
        self._refs: dict[str, int] = {}
        self._send_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._recv_task: asyncio.Task | None = None
        self._send_task: asyncio.Task | None = None
        self._stopping = False
        self.on_tick: OnTick | None = None

    async def start(self) -> None:
        result = self._connect()
        self._conn = await result if asyncio.iscoroutine(result) else result
        self._recv_task = asyncio.create_task(self._recv_loop(), name="wss-recv")
        self._send_task = asyncio.create_task(self._send_loop(), name="wss-send")

    async def stop(self) -> None:
        self._stopping = True
        if self._conn is not None:
            await self._conn.close()
        for t in (self._recv_task, self._send_task):
            if t is not None:
                t.cancel()
        for t in (self._recv_task, self._send_task):
            if t is not None:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    async def subscribe(self, asset_id: str) -> None:
        prev = self._refs.get(asset_id, 0)
        self._refs[asset_id] = prev + 1
        if prev == 0:
            await self._send_queue.put({"type": "market", "assets_ids": [asset_id]})

    async def unsubscribe(self, asset_id: str) -> None:
        if asset_id not in self._refs:
            return
        self._refs[asset_id] -= 1
        if self._refs[asset_id] <= 0:
            del self._refs[asset_id]
            await self._send_queue.put({"type": "unsubscribe", "assets_ids": [asset_id]})

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
            try:
                assert self._conn is not None
                msg = await self._conn.recv()
            except Exception:
                if self._stopping:
                    return
                log.exception("wss recv failed")
                return
            self._handle(msg)

    def _handle(self, msg: dict) -> None:
        if msg.get("event_type") not in ("book", "price_change"):
            return
        asset_id = msg.get("asset_id") or msg.get("market")
        if not asset_id:
            return
        bid = _best_price(msg.get("bids", []), best="max")
        ask = _best_price(msg.get("asks", []), best="min")
        if bid is None or ask is None:
            return
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
```

- [ ] **Step 4: Run tests**

`pytest tests/test_wss_manager.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polyalert/polymarket/wss.py tests/test_wss_manager.py
git commit -m "feat: wss manager with ref-counted subscriptions over a connection abstraction"
```

---

### Task 9: WSS — reconnect, staleness, real websocket adapter

**Files:**
- Modify: `src/polyalert/polymarket/wss.py`
- Modify: `tests/test_wss_manager.py`

- [ ] **Step 1: Add tests for reconnect and staleness**

Append to `tests/test_wss_manager.py`:

```python
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
        await asyncio.sleep(0); await asyncio.sleep(0)

        # Force first conn to fail by closing it
        await conns[0].close()
        # Give recv-loop time to detect and reconnect
        await asyncio.sleep(0.1)
        await asyncio.sleep(0.1)

        assert len(conns) >= 2
        # Second connection got re-subscribe for both tokens
        sent_assets = {
            a for m in conns[1].sent
            if m.get("type") == "market"
            for a in m.get("assets_ids", [])
        }
        assert {"tok-A", "tok-B"}.issubset(sent_assets)
        await mgr.stop()

    asyncio.run(run())
```

- [ ] **Step 2: Run new test, expect failure**

`pytest tests/test_wss_manager.py::test_reconnect_re_subscribes_active_assets -v` → FAIL.

- [ ] **Step 3: Modify `WSSManager` to handle reconnects**

Replace `start`, `_recv_loop`, and add helpers:

```python
    async def start(self) -> None:
        self._main_task = asyncio.create_task(self._run(), name="wss-run")

    async def _run(self) -> None:
        attempt = 0
        while not self._stopping:
            try:
                result = self._connect()
                self._conn = await result if asyncio.iscoroutine(result) else result
                attempt = 0
                # Re-subscribe on reconnect
                for asset_id in list(self._refs):
                    await self._send_queue.put(
                        {"type": "market", "assets_ids": [asset_id]}
                    )
                self._send_task = asyncio.create_task(self._send_loop(), name="wss-send")
                await self._recv_loop()
            except Exception:
                log.exception("wss run loop crashed")
            finally:
                if self._send_task is not None:
                    self._send_task.cancel()
                    try:
                        await self._send_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    self._send_task = None
                if self._conn is not None:
                    try:
                        await self._conn.close()
                    except Exception:
                        pass
                    self._conn = None

            if self._stopping:
                return
            attempt += 1
            await asyncio.sleep(_backoff_seconds(attempt))
```

Update `stop`:

```python
    async def stop(self) -> None:
        self._stopping = True
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass
        for t in (getattr(self, "_main_task", None), self._send_task):
            if t is not None:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
```

Replace `_recv_loop`:

```python
    async def _recv_loop(self) -> None:
        while not self._stopping:
            assert self._conn is not None
            msg = await self._conn.recv()
            self._handle(msg)
```

Add module-level:

```python
def _backoff_seconds(attempt: int) -> float:
    return min(60.0, 2 ** (attempt - 1))
```

Drop the old `_recv_task` reference from `__init__` (replace with `_main_task = None`).

- [ ] **Step 4: Run all WSS tests**

`pytest tests/test_wss_manager.py -v` → all PASS.

- [ ] **Step 5: Add real websocket adapter**

Append to `src/polyalert/polymarket/wss.py`:

```python
import json as _json

import websockets


async def open_polymarket_connection(url: str) -> "PolymarketWebSocketConnection":
    ws = await websockets.connect(url, ping_interval=20, ping_timeout=20)
    return PolymarketWebSocketConnection(ws)


class PolymarketWebSocketConnection:
    def __init__(self, ws):
        self._ws = ws

    async def send(self, msg: dict) -> None:
        await self._ws.send(_json.dumps(msg))

    async def recv(self) -> dict:
        raw = await self._ws.recv()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError:
            return {}
        # Polymarket sometimes returns lists of events; return first if so.
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    async def close(self) -> None:
        await self._ws.close()
```

- [ ] **Step 6: Commit**

```bash
git add src/polyalert/polymarket/wss.py tests/test_wss_manager.py
git commit -m "feat: wss reconnect with re-subscribe and real websocket adapter"
```

---

## Phase 4: Alert Engine

### Task 10: `should_fire` pure logic

**Files:**
- Create: `src/polyalert/engine.py`
- Create: `tests/test_engine_logic.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_engine_logic.py
import pytest
from polyalert.engine import current_price, should_fire
from polyalert.models import Alert, PriceTick


def _alert(*, side, direction, threshold) -> Alert:
    return Alert(
        id=1, user_id=1, market_slug="m", market_title="t", asset_id="tok",
        outcome_label="Yes", side=side, direction=direction,
        threshold=threshold, created_at="2026-05-08",
    )


@pytest.mark.parametrize("side,bid,ask,expected", [
    ("bid", 0.4, 0.5, 0.4),
    ("ask", 0.4, 0.5, 0.5),
    ("mid", 0.4, 0.5, 0.45),
])
def test_current_price(side, bid, ask, expected):
    tick = PriceTick("tok", bid, ask)
    assert current_price(side, tick) == pytest.approx(expected)


def test_above_fires_when_price_meets_threshold():
    tick = PriceTick("tok", 0.55, 0.56)
    assert should_fire(_alert(side="bid", direction="above", threshold=0.55), tick)


def test_above_does_not_fire_when_below():
    tick = PriceTick("tok", 0.50, 0.51)
    assert not should_fire(_alert(side="bid", direction="above", threshold=0.55), tick)


def test_below_fires_when_price_at_threshold():
    tick = PriceTick("tok", 0.30, 0.31)
    assert should_fire(_alert(side="ask", direction="below", threshold=0.31), tick)


def test_below_does_not_fire_when_above():
    tick = PriceTick("tok", 0.50, 0.51)
    assert not should_fire(_alert(side="ask", direction="below", threshold=0.31), tick)


def test_other_asset_id_never_fires():
    tick = PriceTick("OTHER", 0.99, 1.00)
    assert not should_fire(
        _alert(side="ask", direction="above", threshold=0.5),
        tick,
    )
```

- [ ] **Step 2: Run, expect import error**

`pytest tests/test_engine_logic.py -v` → FAIL.

- [ ] **Step 3: Write `src/polyalert/engine.py` (logic only for now)**

```python
from polyalert.models import Alert, PriceTick, Side


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
```

- [ ] **Step 4: Run tests**

`pytest tests/test_engine_logic.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polyalert/engine.py tests/test_engine_logic.py
git commit -m "feat: pure should_fire/current_price logic"
```

---

### Task 11: Alert engine — index, fire flow, integration

**Files:**
- Modify: `src/polyalert/engine.py`
- Create: `tests/test_engine_flow.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_engine_flow.py
import pytest
from polyalert.db import Database
from polyalert.engine import AlertEngine
from polyalert.models import Alert, PriceTick


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
```

- [ ] **Step 2: Run, expect failures**

`pytest tests/test_engine_flow.py -v` → FAIL.

- [ ] **Step 3: Extend `src/polyalert/engine.py`**

Add after the existing logic:

```python
import logging
from typing import Protocol

from polyalert.db import Database

log = logging.getLogger(__name__)


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

    async def start(self) -> None:
        existing = await self._db.load_all_alerts()
        for a in existing:
            self._index.setdefault(a.asset_id, {})[a.id] = a
        for asset_id in self._index:
            await self._wss.subscribe(asset_id)

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

    async def handle_tick(self, tick: PriceTick) -> None:
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

    async def _remove_from_index(self, alert_id: int) -> None:
        for asset_id, bucket in list(self._index.items()):
            if alert_id in bucket:
                del bucket[alert_id]
                if not bucket:
                    del self._index[asset_id]
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
```

- [ ] **Step 4: Run tests**

`pytest tests/test_engine_flow.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polyalert/engine.py tests/test_engine_flow.py
git commit -m "feat: alert engine with index, register/unregister, fire flow"
```

---

## Phase 5: Bot

### Task 12: Inline keyboards

**Files:**
- Create: `src/polyalert/bot/__init__.py`
- Create: `src/polyalert/bot/keyboards.py`
- Create: `tests/test_keyboards.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_keyboards.py
from polyalert.bot.keyboards import (
    direction_kb,
    market_choice_kb,
    outcome_kb,
    side_kb,
)
from polyalert.models import Market, Outcome


def test_outcome_kb_yes_no():
    market = Market(slug="x", title="t", outcomes=[
        Outcome("Yes", "tok-y"), Outcome("No", "tok-n"),
    ], closed=False)
    kb = outcome_kb(market)
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert labels == ["Yes", "No"]


def test_outcome_kb_paginates_when_many():
    outcomes = [Outcome(f"opt-{i}", f"t-{i}") for i in range(20)]
    kb = outcome_kb(Market(slug="x", title="t", outcomes=outcomes, closed=False), page=0)
    rows = kb.inline_keyboard
    # 8 outcomes per page max + nav row
    flat = [btn for row in rows for btn in row]
    nav = [btn for btn in flat if btn.text in ("⏭", "⏮")]
    options = [btn for btn in flat if btn not in nav]
    assert len(options) <= 8
    assert any(btn.text == "⏭" for btn in flat)


def test_side_kb_three_buttons():
    kb = side_kb()
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert set(labels) == {"bid", "ask", "mid"}


def test_direction_kb_two_buttons():
    kb = direction_kb()
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "📈 above" in labels
    assert "📉 below" in labels


def test_market_choice_kb_lists_open_markets_only():
    market_a = Market("a", "A?", [], closed=False)
    market_b = Market("b", "B?", [], closed=True)
    kb = market_choice_kb([market_a, market_b])
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "A?" in labels
    assert "B?" not in labels
```

- [ ] **Step 2: Run, expect import error**

`pytest tests/test_keyboards.py -v` → FAIL.

- [ ] **Step 3: Write `src/polyalert/bot/__init__.py` (empty) and `src/polyalert/bot/keyboards.py`**

```python
# src/polyalert/bot/__init__.py
```

```python
# src/polyalert/bot/keyboards.py
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from polyalert.models import Market

PAGE_SIZE = 8


def market_choice_kb(markets: list[Market]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=m.title, callback_data=f"mkt:{m.slug}")]
        for m in markets if not m.closed
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def outcome_kb(market: Market, page: int = 0) -> InlineKeyboardMarkup:
    start = page * PAGE_SIZE
    page_outcomes = market.outcomes[start : start + PAGE_SIZE]
    rows = [
        [InlineKeyboardButton(text=o.label, callback_data=f"out:{o.token_id}")]
        for o in page_outcomes
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⏮", callback_data=f"page:{page - 1}"))
    if start + PAGE_SIZE < len(market.outcomes):
        nav.append(InlineKeyboardButton(text="⏭", callback_data=f"page:{page + 1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def side_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="bid", callback_data="side:bid"),
        InlineKeyboardButton(text="ask", callback_data="side:ask"),
        InlineKeyboardButton(text="mid", callback_data="side:mid"),
    ]])


def direction_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📈 above", callback_data="dir:above"),
        InlineKeyboardButton(text="📉 below", callback_data="dir:below"),
    ]])


def alert_list_kb(alert_ids: list[int]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"❌ delete #{aid}", callback_data=f"del:{aid}")]
        for aid in alert_ids
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
```

- [ ] **Step 4: Run tests**

`pytest tests/test_keyboards.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polyalert/bot/__init__.py src/polyalert/bot/keyboards.py tests/test_keyboards.py
git commit -m "feat: inline keyboards for FSM and alert list"
```

---

### Task 13: Text templates

**Files:**
- Create: `src/polyalert/bot/messages.py`

- [ ] **Step 1: Write `src/polyalert/bot/messages.py`**

```python
WELCOME = (
    "👋 Send me a Polymarket link and I'll set up a price alert.\n\n"
    "Example:\n"
    "https://polymarket.com/event/will-the-us-confirm-that-aliens-exist-by-may-31\n\n"
    "Commands:\n"
    "/list — your active alerts\n"
    "/cancel — abort the current dialog\n"
    "/help — this message"
)

INVALID_URL = (
    "That's not a valid Polymarket link. Send something like:\n"
    "https://polymarket.com/event/<event-slug>\n"
    "or\n"
    "https://polymarket.com/event/<event-slug>/<market-slug>"
)

MARKET_CLOSED = "This market is closed/resolved — alerts won't help here."

CHOOSE_MARKET = "This event has several markets. Pick one:"

CHOOSE_OUTCOME = "Pick the outcome to track:"

CHOOSE_SIDE = "Which book side?\n• bid (highest buy)\n• ask (lowest sell)\n• mid (midpoint)"

CHOOSE_DIRECTION = "Direction?"

ENTER_THRESHOLD = (
    "Current prices for {outcome}: bid={bid:.4f}, ask={ask:.4f}, mid={mid:.4f}.\n"
    "Send the threshold (a number between 0 and 1)."
)

THRESHOLD_INVALID = "That's not a valid number between 0 and 1."

THRESHOLD_ALREADY_CROSSED = (
    "Current {side} price is {current:.4f}, which already meets your threshold "
    "{threshold:g} ({direction}). Pick another threshold."
)

ALERT_CREATED = "✅ Alert {alert_id}: {description}"

ALERT_LIMIT = "You hit the limit of {limit} active alerts. Delete some via /list."

NO_ALERTS = "You have no active alerts."

ALERT_DELETED = "Deleted."

ALERT_DELETE_FAILED = "Couldn't delete that alert (maybe already gone)."

CANCEL_OK = "Cancelled."

ERROR_GENERIC = "Something went wrong. Try again later."
```

- [ ] **Step 2: Commit**

```bash
git add src/polyalert/bot/messages.py
git commit -m "feat: bot text templates"
```

---

### Task 14: FSM state definitions

**Files:**
- Create: `src/polyalert/bot/fsm.py`

- [ ] **Step 1: Write `src/polyalert/bot/fsm.py`**

```python
from aiogram.fsm.state import State, StatesGroup


class AlertCreation(StatesGroup):
    waiting_market_choice = State()
    waiting_outcome = State()
    waiting_side = State()
    waiting_direction = State()
    waiting_threshold = State()


# Keys we put into FSM context (data dict)
K_EVENT_SLUG = "event_slug"
K_MARKET_SLUG = "market_slug"
K_MARKET_TITLE = "market_title"
K_ASSET_ID = "asset_id"
K_OUTCOME_LABEL = "outcome_label"
K_SIDE = "side"
K_DIRECTION = "direction"
K_OUTCOMES_PAGE = "outcomes_page"
```

- [ ] **Step 2: Commit**

```bash
git add src/polyalert/bot/fsm.py
git commit -m "feat: FSM states and context keys for alert creation"
```

---

### Task 15: Notifier wrapper (Telegram, with retry + 403 handling)

**Files:**
- Create: `src/polyalert/notifier.py`
- Create: `tests/test_notifier.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_notifier.py
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
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
```

- [ ] **Step 2: Run, expect failures**

`pytest tests/test_notifier.py -v` → FAIL.

- [ ] **Step 3: Write `src/polyalert/notifier.py`**

```python
import logging

from aiogram.exceptions import TelegramForbiddenError

from polyalert.db import Database

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, *, bot, db: Database):
        self._bot = bot
        self._db = db

    async def send(self, user_id: int, text: str) -> None:
        try:
            await self._bot.send_message(user_id, text)
            return
        except TelegramForbiddenError:
            log.info("user %s blocked the bot, removing", user_id)
            await self._db.delete_user(user_id)
            return
        except Exception as e:
            log.warning("send to %s failed (1st): %s", user_id, e)

        # One retry
        try:
            await self._bot.send_message(user_id, text)
        except TelegramForbiddenError:
            await self._db.delete_user(user_id)
        except Exception as e:
            log.error("send to %s failed (2nd, dropping): %s", user_id, e)
```

- [ ] **Step 4: Run tests**

`pytest tests/test_notifier.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polyalert/notifier.py tests/test_notifier.py
git commit -m "feat: telegram notifier with retry and 403 cleanup"
```

---

### Task 16: Bot handlers — `/start`, `/help`, `/list`, `/cancel`

**Files:**
- Create: `src/polyalert/bot/handlers.py`

These handlers don't have rich logic — we'll smoke-test them manually in Task 19. Keep them small and pull all text from `messages.py`.

- [ ] **Step 1: Write `src/polyalert/bot/handlers.py`**

```python
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from polyalert.bot import messages as msg
from polyalert.bot.fsm import AlertCreation
from polyalert.bot.keyboards import alert_list_kb
from polyalert.db import Database
from polyalert.engine import AlertEngine

router = Router()

# Stored at module-level once the application wires them in __main__.py
_db: Database | None = None
_engine: AlertEngine | None = None


def wire(*, db: Database, engine: AlertEngine) -> None:
    global _db, _engine
    _db = db
    _engine = engine


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    assert _db is not None
    await _db.upsert_user(message.from_user.id)
    await message.answer(msg.WELCOME)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(msg.WELCOME)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(msg.CANCEL_OK)


@router.message(Command("list"))
async def cmd_list(message: Message) -> None:
    assert _db is not None
    alerts = await _db.list_alerts(message.from_user.id)
    if not alerts:
        await message.answer(msg.NO_ALERTS)
        return
    text = "\n".join(a.describe() for a in alerts)
    await message.answer(text, reply_markup=alert_list_kb([a.id for a in alerts]))


@router.callback_query(F.data.startswith("del:"))
async def cb_delete(query: CallbackQuery) -> None:
    assert _db is not None and _engine is not None
    alert_id = int(query.data.split(":", 1)[1])
    ok = await _engine.unregister(alert_id, user_id=query.from_user.id)
    await query.answer(msg.ALERT_DELETED if ok else msg.ALERT_DELETE_FAILED)
```

- [ ] **Step 2: Quick lint check**

`ruff check src/polyalert/bot/handlers.py` → no errors.

- [ ] **Step 3: Commit**

```bash
git add src/polyalert/bot/handlers.py
git commit -m "feat: handlers for /start, /help, /list, /cancel and delete callback"
```

---

### Task 17: Bot handlers — URL → market choice → outcome → side → direction → threshold

**Files:**
- Modify: `src/polyalert/bot/handlers.py`
- Create: `src/polyalert/polymarket/__init__.py` re-exports (optional)

This is the biggest single task — but each FSM transition is a discrete handler, so it stays tractable.

- [ ] **Step 1: Append to `src/polyalert/bot/handlers.py`**

Add imports near the top:

```python
import logging

from polyalert.bot.fsm import (
    K_ASSET_ID, K_DIRECTION, K_EVENT_SLUG, K_MARKET_SLUG, K_MARKET_TITLE,
    K_OUTCOME_LABEL, K_OUTCOMES_PAGE, K_SIDE,
)
from polyalert.bot.keyboards import (
    direction_kb, market_choice_kb, outcome_kb, side_kb,
)
from polyalert.config import Settings
from polyalert.db import AlertLimitExceeded
from polyalert.engine import current_price
from polyalert.models import PriceTick
from polyalert.polymarket.rest import EventNotFound, MarketNotFound, PolymarketRest
from polyalert.polymarket.url import InvalidURL, parse_polymarket_url

log = logging.getLogger(__name__)
```

Extend the wire signature so handlers can reach the REST client and settings:

Replace the `wire` function and globals:

```python
_db: Database | None = None
_engine: AlertEngine | None = None
_rest: PolymarketRest | None = None
_settings: Settings | None = None


def wire(
    *,
    db: Database,
    engine: AlertEngine,
    rest: PolymarketRest,
    settings: Settings,
) -> None:
    global _db, _engine, _rest, _settings
    _db = db
    _engine = engine
    _rest = rest
    _settings = settings
```

Add handlers (keep adding to the bottom of the file):

```python
@router.message(F.text.regexp(r"https?://(?:www\.)?polymarket\.com/"))
async def msg_url(message: Message, state: FSMContext) -> None:
    assert _rest is not None
    try:
        event_slug, market_slug = parse_polymarket_url(message.text or "")
    except InvalidURL:
        await message.answer(msg.INVALID_URL)
        return

    try:
        if market_slug:
            market = await _rest.get_market(market_slug)
            if market.closed:
                await message.answer(msg.MARKET_CLOSED)
                return
            await state.update_data({
                K_EVENT_SLUG: event_slug,
                K_MARKET_SLUG: market_slug,
                K_MARKET_TITLE: market.title,
            })
            await _ask_outcome(message, state, market)
            return

        assert event_slug is not None
        event = await _rest.get_event(event_slug)
        open_markets = [m for m in event.markets if not m.closed]
        if not open_markets:
            await message.answer(msg.MARKET_CLOSED)
            return
        if len(open_markets) == 1:
            single = open_markets[0]
            await state.update_data({
                K_EVENT_SLUG: event_slug,
                K_MARKET_SLUG: single.slug,
                K_MARKET_TITLE: single.title,
            })
            await _ask_outcome(message, state, single)
            return

        await state.update_data({K_EVENT_SLUG: event_slug})
        await state.set_state(AlertCreation.waiting_market_choice)
        await message.answer(msg.CHOOSE_MARKET, reply_markup=market_choice_kb(open_markets))
    except (MarketNotFound, EventNotFound):
        await message.answer(msg.INVALID_URL)
    except Exception:
        log.exception("URL handler failed")
        await message.answer(msg.ERROR_GENERIC)


async def _ask_outcome(message_or_query, state: FSMContext, market) -> None:
    await state.update_data({K_OUTCOMES_PAGE: 0})
    await state.set_state(AlertCreation.waiting_outcome)
    if hasattr(message_or_query, "answer") and hasattr(message_or_query, "from_user"):
        await message_or_query.answer(msg.CHOOSE_OUTCOME, reply_markup=outcome_kb(market))


@router.callback_query(AlertCreation.waiting_market_choice, F.data.startswith("mkt:"))
async def cb_pick_market(query: CallbackQuery, state: FSMContext) -> None:
    assert _rest is not None
    await query.answer()
    market_slug = query.data.split(":", 1)[1]
    market = await _rest.get_market(market_slug)
    await state.update_data({
        K_MARKET_SLUG: market_slug,
        K_MARKET_TITLE: market.title,
    })
    await state.update_data({K_OUTCOMES_PAGE: 0})
    await state.set_state(AlertCreation.waiting_outcome)
    await query.message.answer(msg.CHOOSE_OUTCOME, reply_markup=outcome_kb(market))


@router.callback_query(AlertCreation.waiting_outcome, F.data.startswith("page:"))
async def cb_outcome_page(query: CallbackQuery, state: FSMContext) -> None:
    assert _rest is not None
    await query.answer()
    page = int(query.data.split(":", 1)[1])
    data = await state.get_data()
    market = await _rest.get_market(data[K_MARKET_SLUG])
    await state.update_data({K_OUTCOMES_PAGE: page})
    await query.message.edit_reply_markup(reply_markup=outcome_kb(market, page=page))


@router.callback_query(AlertCreation.waiting_outcome, F.data.startswith("out:"))
async def cb_pick_outcome(query: CallbackQuery, state: FSMContext) -> None:
    assert _rest is not None
    await query.answer()
    token_id = query.data.split(":", 1)[1]
    data = await state.get_data()
    market = await _rest.get_market(data[K_MARKET_SLUG])
    label = next((o.label for o in market.outcomes if o.token_id == token_id), token_id)
    await state.update_data({K_ASSET_ID: token_id, K_OUTCOME_LABEL: label})
    await state.set_state(AlertCreation.waiting_side)
    await query.message.answer(msg.CHOOSE_SIDE, reply_markup=side_kb())


@router.callback_query(AlertCreation.waiting_side, F.data.startswith("side:"))
async def cb_pick_side(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    side = query.data.split(":", 1)[1]
    await state.update_data({K_SIDE: side})
    await state.set_state(AlertCreation.waiting_direction)
    await query.message.answer(msg.CHOOSE_DIRECTION, reply_markup=direction_kb())


@router.callback_query(AlertCreation.waiting_direction, F.data.startswith("dir:"))
async def cb_pick_direction(query: CallbackQuery, state: FSMContext) -> None:
    assert _rest is not None
    await query.answer()
    direction = query.data.split(":", 1)[1]
    await state.update_data({K_DIRECTION: direction})
    data = await state.get_data()
    tick = await _fetch_current_tick(data[K_ASSET_ID])
    if tick is None:
        await query.message.answer(msg.ERROR_GENERIC)
        await state.clear()
        return
    await state.set_state(AlertCreation.waiting_threshold)
    await query.message.answer(msg.ENTER_THRESHOLD.format(
        outcome=data[K_OUTCOME_LABEL], bid=tick.bid, ask=tick.ask, mid=tick.mid,
    ))


@router.message(AlertCreation.waiting_threshold)
async def msg_threshold(message: Message, state: FSMContext) -> None:
    assert _db is not None and _engine is not None and _settings is not None
    raw = (message.text or "").strip().replace(",", ".")
    try:
        threshold = float(raw)
    except ValueError:
        await message.answer(msg.THRESHOLD_INVALID)
        return
    if not (0.0 < threshold < 1.0):
        await message.answer(msg.THRESHOLD_INVALID)
        return

    data = await state.get_data()
    tick = await _fetch_current_tick(data[K_ASSET_ID])
    if tick is None:
        await message.answer(msg.ERROR_GENERIC)
        await state.clear()
        return
    side = data[K_SIDE]
    direction = data[K_DIRECTION]
    cur = current_price(side, tick)

    already = (direction == "above" and cur >= threshold) or \
              (direction == "below" and cur <= threshold)
    if already:
        await message.answer(msg.THRESHOLD_ALREADY_CROSSED.format(
            side=side, current=cur, threshold=threshold, direction=direction,
        ))
        return

    try:
        await _db.upsert_user(message.from_user.id)
        alert = await _db.create_alert(
            user_id=message.from_user.id,
            market_slug=data[K_MARKET_SLUG],
            market_title=data[K_MARKET_TITLE],
            asset_id=data[K_ASSET_ID],
            outcome_label=data[K_OUTCOME_LABEL],
            side=side,
            direction=direction,
            threshold=threshold,
            max_per_user=_settings.max_alerts_per_user,
        )
    except AlertLimitExceeded:
        await message.answer(msg.ALERT_LIMIT.format(limit=_settings.max_alerts_per_user))
        await state.clear()
        return

    await _engine.register(alert)
    await state.clear()
    await message.answer(msg.ALERT_CREATED.format(
        alert_id=alert.id, description=alert.describe(),
    ))


async def _fetch_current_tick(asset_id: str) -> "PriceTick | None":
    """Fetch a fresh tick from REST so we can show prices and validate threshold.

    Polymarket exposes price book via gamma's price endpoint:
      GET <rest-base>/price?token_id=<id>&side=BUY  → best bid
      GET <rest-base>/price?token_id=<id>&side=SELL → best ask
    """
    assert _rest is not None
    import httpx
    try:
        bid_resp = await _rest._client.get("/price", params={"token_id": asset_id, "side": "BUY"})
        ask_resp = await _rest._client.get("/price", params={"token_id": asset_id, "side": "SELL"})
        bid_resp.raise_for_status(); ask_resp.raise_for_status()
        bid = float(bid_resp.json().get("price", 0))
        ask = float(ask_resp.json().get("price", 0))
        if bid <= 0 or ask <= 0:
            return None
        return PriceTick(asset_id=asset_id, bid=bid, ask=ask)
    except (httpx.HTTPError, ValueError, KeyError):
        return None
```

> Note: `_fetch_current_tick` reaches into `_rest._client`. To keep the public API clean, prefer adding a `get_price(token_id, side)` method on `PolymarketRest`. Do that as part of this task before committing.

- [ ] **Step 2: Add `get_price` to `PolymarketRest`**

Edit `src/polyalert/polymarket/rest.py`. Add method:

```python
    async def get_price(self, token_id: str, side: str) -> float:
        """side is 'BUY' for best bid or 'SELL' for best ask."""
        resp = await self._client.get("/price", params={"token_id": token_id, "side": side})
        resp.raise_for_status()
        return float(resp.json().get("price", 0))
```

Replace `_fetch_current_tick` to use it:

```python
async def _fetch_current_tick(asset_id: str) -> "PriceTick | None":
    assert _rest is not None
    try:
        bid = await _rest.get_price(asset_id, "BUY")
        ask = await _rest.get_price(asset_id, "SELL")
    except Exception:
        log.exception("price fetch failed")
        return None
    if bid <= 0 or ask <= 0:
        return None
    return PriceTick(asset_id=asset_id, bid=bid, ask=ask)
```

- [ ] **Step 3: Quick lint check**

```bash
ruff check src/polyalert/
```

Fix any issues reported.

- [ ] **Step 4: Run full test suite**

```bash
pytest -q
```

All tests should still pass.

- [ ] **Step 5: Commit**

```bash
git add src/polyalert/bot/handlers.py src/polyalert/polymarket/rest.py
git commit -m "feat: full alert-creation FSM (URL → market → outcome → side → direction → threshold)"
```

---

## Phase 6: Wiring & deployment

### Task 18: Application entrypoint

**Files:**
- Create: `src/polyalert/__main__.py`

- [ ] **Step 1: Write `src/polyalert/__main__.py`**

```python
import asyncio
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

    rest = PolymarketRest(settings.polymarket_rest_url)
    bot = Bot(token=settings.telegram_bot_token)
    notifier = TelegramNotifier(bot=bot, db=db)

    wss = WSSManager(connect=lambda: open_polymarket_connection(settings.polymarket_wss_url))
    engine = AlertEngine(db=db, notifier=notifier, wss=wss)
    wss.on_tick = lambda tick: asyncio.create_task(engine.handle_tick(tick))

    handlers.wire(db=db, engine=engine, rest=rest, settings=settings)

    dp = Dispatcher()
    dp.include_router(handlers.router)

    await wss.start()
    await engine.start()
    log.info("polyalert started")
    try:
        await dp.start_polling(bot)
    finally:
        log.info("shutting down")
        await wss.stop()
        await rest.close()
        await bot.session.close()
        await db.close()


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test locally**

In one terminal:

```bash
source .venv/bin/activate
python -m polyalert
```

Expected: log line `polyalert started`, no traceback. In Telegram, message `@your_bot_username` with `/start` and verify it answers. Send a Polymarket URL, walk through FSM, create an alert. Check `/list`. Delete via the inline button.

- [ ] **Step 3: Commit**

```bash
git add src/polyalert/__main__.py
git commit -m "feat: application entrypoint wiring everything together"
```

---

### Task 19: systemd unit and deploy docs

**Files:**
- Create: `systemd/polyalert.service`
- Modify: `README.md`

- [ ] **Step 1: Write `systemd/polyalert.service`**

```ini
[Unit]
Description=PolyAlert Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=polyalert
Group=polyalert
WorkingDirectory=/opt/polyalert
EnvironmentFile=/opt/polyalert/.env
ExecStart=/opt/polyalert/.venv/bin/python -m polyalert
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Append deployment section to `README.md`**

```markdown
## Production deploy (VPS, systemd)

On the VPS (as root or with sudo):

```bash
useradd -r -m -d /opt/polyalert -s /bin/bash polyalert
cd /opt/polyalert
sudo -u polyalert git clone <your-repo-url> .
sudo -u polyalert python3.12 -m venv .venv
sudo -u polyalert .venv/bin/pip install -e .

# Create .env (TELEGRAM_BOT_TOKEN at minimum)
sudo -u polyalert cp .env.example .env
sudo -u polyalert vim .env
sudo chmod 600 .env
sudo chown polyalert:polyalert .env

# Install service
cp systemd/polyalert.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now polyalert
journalctl -u polyalert -f
```

### Backups

Add to root crontab (`crontab -e`):

```cron
0 4 * * * cp /opt/polyalert/polyalert.db /opt/polyalert/backups/polyalert.db.$(date +\%F).bak && find /opt/polyalert/backups -name 'polyalert.db.*.bak' -mtime +7 -delete
```

Pre-create the directory: `sudo -u polyalert mkdir -p /opt/polyalert/backups`.
```

- [ ] **Step 3: Commit**

```bash
git add systemd/polyalert.service README.md
git commit -m "feat: systemd unit and deployment instructions"
```

---

### Task 20: Final verification & smoke

**Files:** _no new files_

- [ ] **Step 1: Run the full test suite**

```bash
pytest -q
ruff check src/ tests/
```

Both must succeed.

- [ ] **Step 2: Run a real end-to-end smoke**

With the bot running locally and a real Polymarket market open:

1. `/start` → expect welcome
2. Send a real Polymarket URL → expect outcome buttons
3. Pick `Yes` → side prompt
4. Pick `mid` → direction prompt
5. Pick `above` → threshold prompt with current prices
6. Send a threshold slightly above mid (e.g. mid+0.01) → expect "Alert created"
7. `/list` → expect the alert
8. Wait for natural price movement OR set threshold very close to current to trigger fast → expect notification
9. After firing, `/list` → expect empty
10. Create another, then delete via inline button → expect "Deleted."

- [ ] **Step 3: Tag the release**

```bash
git tag -a v0.1.0 -m "PolyAlert v0.1.0 — first working version"
```

---

## Self-review notes (filled by plan author)

**Spec coverage check:**
- Public bot, multi-user → handlers + per-user limits ✅ (Tasks 6, 17)
- VPS + systemd → Task 19 ✅
- Python + asyncio → all tasks ✅
- WSS real-time + REST init → Tasks 7, 8, 9 ✅
- Buttons + commands UX → Tasks 12, 16, 17 ✅
- One-shot alerts → engine deletes after fire (Task 11) ✅
- bid/ask/mid choice → Tasks 12, 17 ✅
- explicit above/below choice → Tasks 12, 17 ✅
- 10 alerts limit → Task 6 (`AlertLimitExceeded`) ✅
- Multi-outcome support with pagination → Task 12 (`PAGE_SIZE`) ✅
- Multi-market events with picker → Task 17 (`waiting_market_choice`) ✅
- Closed market rejection → Task 17 ✅
- Threshold "already crossed" rejection → Task 17 ✅
- 403 → delete user → Task 15 ✅
- WSS reconnect with re-subscribe → Task 9 ✅
- Telegram retry once → Task 15 ✅
- structlog/logging → entrypoint sets `logging.basicConfig` ✅
- `.env` config via pydantic-settings → Task 3 ✅

**Open items intentionally deferred (YAGNI):**
- WSS staleness 5-min check: spec calls for it but the websockets library's ping_interval=20 + ping_timeout=20 already triggers reconnect on broken sockets. If we discover actual stale-without-disconnect symptoms in production, add an explicit `last_message_at` per asset_id and force reconnect — but not before observing the symptom.
- structlog: stdlib `logging` is sufficient for v0.1; switch to structlog if/when log volume warrants structured search.

These are explicit deferrals, not gaps.
