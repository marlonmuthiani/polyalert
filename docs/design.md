# PolyAlert — дизайн

**Дата:** 2026-05-08
**Статус:** Draft (ожидает review пользователем)

## Цель

Telegram-бот для алертов цен на рынках Polymarket. Пользователь присылает ссылку на конкретный рынок, выбирает исход, сторону книги (bid/ask/mid), направление (выше/ниже) и порог. Когда цена пересекает порог — приходит уведомление в Telegram.

## Контекст и решения

| Параметр | Значение | Обоснование |
|---|---|---|
| Аудитория | Публичный бот | Любой может подписаться |
| Хостинг | VPS (Debian/Ubuntu) | Один сервер, systemd |
| Стек | Python 3.12+, asyncio | Богатая экосистема для Telegram + WSS |
| Telegram-фреймворк | aiogram 3.x | Современный, FSM, async-нативный |
| Источник цен | Polymarket WSS (CLOB) | Real-time, минимум rate-limit |
| База | SQLite + WAL (через `aiosqlite`) | Малый объём данных, один процесс |
| UX | Команды + inline-кнопки | Баланс простоты и гибкости |
| Алерт | One-shot | Сработал → удалился. Без flapping. |
| Лимит | 10 активных алертов на пользователя | Защита от abuse, контроль WSS-подписок |
| Деплой | systemd, без Docker | Минимум сложности на VPS |

## Архитектура

Один Python-процесс, asyncio. Внутри — три логических слоя, общающихся через прямые вызовы и асинхронные очереди.

```
                ┌───────────────────────┐
                │    Telegram User      │
                └──────────┬────────────┘
                  long-poll │
                ┌──────────▼────────────┐
                │   Python process      │
                │ ┌─────────┐ ┌────────┐│
                │ │  Bot    │ │ Alert  ││
                │ │(aiogram)│◄┤ Engine ││
                │ └────┬────┘ └────▲───┘│
                │      │           │    │
                │      ▼           │    │
                │  ┌───────────────┴──┐ │
                │  │  SQLite (WAL)    │ │
                │  └──────────────────┘ │
                │           ▲           │
                │  ┌────────┴─────────┐ │
                │  │   WSS Manager    │ │
                │  └────────┬─────────┘ │
                └───────────┼───────────┘
                  REST init │  WSS subs
                ┌───────────▼───────────┐
                │   Polymarket APIs     │
                │   gamma + clob WSS    │
                └───────────────────────┘
```

## Компоненты

### 1. Bot layer (`src/polyalert/bot/`)

**Команды:**
- `/start` — приветствие, регистрация пользователя в БД
- `/help` — краткая справка
- `/list` — список активных алертов с inline-кнопкой «❌ удалить» у каждого
- `/cancel` — отменить текущий FSM-диалог

**URL handler:** ловит сообщения, начинающиеся с `https://polymarket.com/...`, запускает FSM создания алерта.

**FSM состояния (создание алерта):**
1. `waiting_market_choice` — если URL = event с >1 sub-market, показываем кнопки
2. `waiting_outcome` — кнопки исходов (YES/NO или больше для multi-outcome)
3. `waiting_side` — кнопки `bid` / `ask` / `mid`
4. `waiting_direction` — кнопки `📈 выше` / `📉 ниже`
5. `waiting_threshold` — текстовый ввод числа

**Клавиатуры:** inline keyboards с пагинацией для multi-outcome рынков (>8 кнопок).

### 2. Polymarket client (`src/polyalert/polymarket/`)

**`url.py`** — парсер URL Polymarket:
- `polymarket.com/event/<event-slug>` → `(event_slug, None)`
- `polymarket.com/event/<event-slug>/<market-slug>` → `(event_slug, market_slug)`
- Любой другой формат → `InvalidURL`

**`rest.py`** — клиент `https://gamma-api.polymarket.com`:
- `get_event(slug)` → `Event` со списком `markets`
- `get_market(slug)` → `Market` с `outcomes`, `clob_token_ids`, `closed`, `active`
- `get_prices(token_id)` → текущие bid/ask/mid (используется для отображения и валидации)

**`wss.py`** — менеджер `wss://ws-subscriptions-clob.polymarket.com/ws/market`:
- Single connection, auto-reconnect с exponential backoff (1→2→4→…→60s)
- Ref-counted set подписок: `{token_id: ref_count}`
- API: `subscribe(token_id)`, `unsubscribe(token_id)` — отписка только когда ref достигает 0
- На reconnect: повторно подписываемся на все активные token_id
- Staleness check: если 5 минут нет update'а на token — форсим reconnect
- Push price-tick'и в `asyncio.Queue`, который читает Engine

### 3. Alert Engine (`src/polyalert/engine.py`)

In-memory индекс `asset_id → list[Alert]`, синхронизированный с БД.

**Логика срабатывания** (one-shot):

```python
def should_fire(alert: Alert, tick: PriceTick) -> bool:
    price = tick.bid if alert.side == 'bid' else \
            tick.ask if alert.side == 'ask' else \
            (tick.bid + tick.ask) / 2  # mid
    if alert.direction == 'above':
        return price >= alert.threshold
    return price <= alert.threshold
```

**Валидация при создании:** текущая цена должна быть на противоположной стороне порога. Иначе — отказ «цена уже X, выбери другой порог».

**Жизненный цикл:**
- Создание: в БД → в индекс → `wss.subscribe(token_id)`
- Срабатывание: уведомление → удаление из БД и индекса → `wss.unsubscribe(token_id)`
- Удаление пользователем: то же без уведомления
- Старт процесса: загрузка всех алертов из БД → подписка на все уникальные token_id

### 4. Storage (`src/polyalert/db.py`)

SQLite в WAL-режиме через `aiosqlite`.

**Schema:**

```sql
CREATE TABLE users (
    telegram_id INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL  -- ISO timestamp
);

CREATE TABLE alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(telegram_id),
    market_slug   TEXT NOT NULL,
    market_title  TEXT NOT NULL,
    asset_id      TEXT NOT NULL,        -- Polymarket CLOB token_id
    outcome_label TEXT NOT NULL,        -- 'Yes', 'No', or other
    side          TEXT NOT NULL CHECK (side IN ('bid','ask','mid')),
    direction     TEXT NOT NULL CHECK (direction IN ('above','below')),
    threshold     REAL NOT NULL CHECK (threshold > 0 AND threshold < 1),
    created_at    TEXT NOT NULL
);

CREATE INDEX idx_alerts_asset_id ON alerts(asset_id);
CREATE INDEX idx_alerts_user_id  ON alerts(user_id);
```

Миграции — простой numbered migration runner на старте (`migrations/001_init.sql`, ...).

### 5. Config (`src/polyalert/config.py`)

`pydantic-settings` загружает из `.env`:
- `TELEGRAM_BOT_TOKEN` (required)
- `POLYMARKET_REST_URL` (default: `https://gamma-api.polymarket.com`)
- `POLYMARKET_WSS_URL` (default: `wss://ws-subscriptions-clob.polymarket.com/ws/market`)
- `DB_PATH` (default: `./polyalert.db`)
- `MAX_ALERTS_PER_USER` (default: `10`)
- `LOG_LEVEL` (default: `INFO`)
- `WSS_STALE_TIMEOUT_SECONDS` (default: `300`)

## Data flow: создание алерта

1. Пользователь присылает URL Polymarket
2. `polymarket/url.py` извлекает `(event_slug, market_slug?)`
3. REST: `get_event(event_slug)`
4. Если `market_slug` не указан и markets > 1 → бот шлёт кнопки выбора маркета (FSM: `waiting_market_choice`)
5. Если рынок закрыт/resolved (`closed=true` или `active=false`) → отказ «рынок закрыт»
6. Бот показывает заголовок маркета + текущие цены каждого outcome
7. FSM: `waiting_outcome` → пользователь выбирает исход (YES/NO/other) → сохраняем `outcome_label` и `asset_id` (token_id)
8. FSM: `waiting_side` → пользователь выбирает bid/ask/mid
9. FSM: `waiting_direction` → пользователь выбирает выше/ниже
10. Бот показывает текущую цену выбранной стороны и просит ввести порог
11. FSM: `waiting_threshold` → пользователь шлёт число
12. Валидация: `0 < threshold < 1`; текущая цена на противоположной стороне порога; у пользователя <10 активных алертов
13. Сохраняем в БД, добавляем в индекс engine, `wss.subscribe(asset_id)`
14. «✅ Алерт #N: <Title> · YES · mid · ↑ 0.55»

## Data flow: срабатывание

1. WSS push → парсим в `PriceTick(asset_id, bid, ask, mid)`
2. WSSManager кладёт в очередь
3. Engine берёт из очереди, ищет алерты по `asset_id` в in-memory индексе
4. Для каждого — проверка `should_fire`
5. Если сработал:
   - Telegram message: `🔔 <Title>\n<outcome> <side> = <price>\n(порог: <threshold> <↑/↓>)`
   - Удаляем из БД и индекса
   - `wss.unsubscribe(asset_id)` (decrement ref; если 0 — реальный unsubscribe)

## Обработка ошибок

| Сценарий | Обработка |
|---|---|
| Невалидный URL | Сообщение с примером валидной ссылки |
| Закрытый/resolved market | Отказ при создании алерта |
| Telegram 403 (юзер заблокировал бота) | Удалить пользователя и все его алерты |
| WSS disconnect | Exponential backoff (1→60s), на reconnect — re-subscribe всех asset_id |
| WSS «тишина» >5 мин | Принудительный reconnect |
| Telegram send fail | Один retry; затем алерт всё равно удаляется (не спамим) |
| REST gamma-api недоступен | Сообщение «временные проблемы, попробуй позже» |
| Ввод порога вне (0,1) | Ошибка валидации, переспросить |
| Превышен лимит 10 | Отказ с предложением `/list` для удаления |
| Текущая цена уже за порогом | Отказ «цена уже X, выбери другой порог» |

## Логирование и наблюдаемость

- `structlog` или stdlib `logging`, JSON-формат в stdout (journald подхватит)
- Логируем: создание/удаление/срабатывание алерта, WSS reconnect, parse errors, REST errors
- Без PII в логах (telegram_id оставляем, но не username)

## Безопасность

- `.env` файл `chmod 600`
- Никаких секретов в коде или логах
- Polymarket API публичный — никаких ключей
- Telegram bot token — только через `.env`
- Валидация всех пользовательских вводов (URL, числа)

## Тестирование

**Unit (pytest):**
- `polymarket/url.py` — все варианты URL
- `engine.should_fire` — все комбинации (side × direction × ценовые сценарии)
- FSM transitions — happy path и validation errors
- Валидация порога

**Integration:**
- Реальный SQLite в `tmp_path`, миграции, CRUD алертов
- AlertEngine с искусственной очередью PriceTick'ов
- WSSManager с фейковым WSS-сервером (или mock через `pytest-asyncio`)

**E2E (опционально):**
- Mock Telegram API + mock WSS, полный сценарий

**Подход:** TDD — тесты пишем перед кодом для каждого юнита.

## Деплой

**VPS:** Debian/Ubuntu, ≥1 GB RAM, Python 3.12.

**Установка:**
```bash
git clone <repo> /opt/polyalert
cd /opt/polyalert
python3.12 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env  # заполнить TELEGRAM_BOT_TOKEN
chmod 600 .env
```

**systemd unit (`/etc/systemd/system/polyalert.service`):**
```ini
[Unit]
Description=PolyAlert Telegram Bot
After=network.target

[Service]
Type=simple
User=polyalert
WorkingDirectory=/opt/polyalert
ExecStart=/opt/polyalert/.venv/bin/python -m polyalert
EnvironmentFile=/opt/polyalert/.env
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Backup:** cron daily `cp polyalert.db backups/polyalert.db.$(date +%F).bak`, ротация 7 дней.

**Логи:** `journalctl -u polyalert -f`.

## Структура проекта

```
polyalert/
├── pyproject.toml
├── .env.example
├── README.md
├── systemd/polyalert.service
├── docs/design.md
├── src/polyalert/
│   ├── __init__.py
│   ├── __main__.py            # entrypoint, wires everything
│   ├── config.py              # pydantic-settings
│   ├── db.py                  # aiosqlite + migrations
│   ├── models.py              # dataclasses: Alert, Market, PriceTick, Event
│   ├── engine.py              # AlertEngine
│   ├── polymarket/
│   │   ├── __init__.py
│   │   ├── url.py             # URL parser
│   │   ├── rest.py            # gamma API client (httpx)
│   │   └── wss.py             # WSS manager (websockets)
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── handlers.py        # command + URL + callback handlers
│   │   ├── fsm.py             # FSM state definitions
│   │   ├── keyboards.py       # inline kb factories (with pagination)
│   │   └── messages.py        # text templates
│   └── migrations/
│       └── 001_init.sql
└── tests/
    ├── conftest.py
    ├── test_url.py
    ├── test_engine.py
    ├── test_db.py
    ├── test_fsm.py
    └── test_polymarket_rest.py
```

## Что НЕ входит в первую версию (YAGNI)

- Repeating-алерты (только one-shot)
- Web-dashboard или Mini App
- Поддержка других prediction-маркетов (только Polymarket)
- Графики цен
- Алерты по объёму, ликвидности, спреду
- Платная подписка / премиум-лимиты
- Multi-server / horizontal scaling (один процесс на одном VPS)
- Уведомления e-mail/SMS/прочее (только Telegram)

Это можно добавить позже, если будет нужно.

## Открытые вопросы

Все ключевые решения зафиксированы. Если в ходе реализации обнаружится неоднозначность — фиксируем здесь и решаем с пользователем.
