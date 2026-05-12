# PolyAlert

A Telegram bot that watches [Polymarket](https://polymarket.com/) prediction-market prices and pings you when an outcome's price crosses a threshold you set.

Send the bot a market link, pick an outcome (`YES` / `NO` / multi-outcome), pick a book side (`bid` / `ask` / `mid`), pick a direction (`above` / `below`), enter a threshold — that's the alert. When the live price crosses it, you get a one-shot Telegram notification.

```
🔔 Will the US confirm that aliens exist by May 31?
Yes · mid = 0.5500
(threshold: 0.55 ↑)
```

## Why

Polymarket's UI doesn't notify you. Alerting bots that exist are either paid SaaS, parse the homepage, or poll REST endpoints with seconds-to-minutes lag.

PolyAlert connects directly to Polymarket's CLOB WebSocket and reacts to price changes as they happen, with one shared connection multiplexed across every active alert.

## Features

- **Real-time** — single WebSocket to `wss-subscriptions-clob.polymarket.com`, ref-counted subscriptions, auto-reconnect with exponential backoff, 5-minute staleness watchdog.
- **Public multi-user** — every Telegram user gets their own isolated set of alerts (10 per user by default).
- **One-shot** — alert fires once, then deletes itself. No flapping, no spam.
- **Full flexibility** — pick the outcome (handles multi-outcome events with pagination), pick the book side (bid/ask/mid), pick the direction (above/below), pick the threshold. Any combination.
- **Set-replace WSS protocol-aware** — every subscription change re-sends the full active asset set in one batched message (Polymarket's WSS treats subscribe as set-replace, not additive; the discovery is documented in commit history).
- **Observable** — `/status` shows uptime, WSS connection state, subscription set, tick counters, last-message age, fire totals.
- **Operational** — systemd unit, daily SQLite backups, no exposed ports, runs as a dedicated unprivileged user.

## Commands

| Command | What it does |
|---------|-------------|
| `/start` | Welcome + register |
| `/help` | Same as `/start` |
| `/list` | Your active alerts with current prices |
| `/cancel` | Abort the current alert-creation dialog |
| `/status` | Bot health (owner only) |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Telegram (long-poll)                  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                  Python process (asyncio)                │
│                                                          │
│   aiogram 3 ────────► AlertEngine ◄──── WSSManager       │
│      handlers           index +           one ws.client  │
│      FSM                tick cache        ref-counted    │
│      keyboards          consumer          batched subs   │
│         │                  │                  │          │
│         └──────────┬───────┴──────────────────┘          │
│                    ▼                                     │
│             SQLite (WAL, aiosqlite)                      │
└──────────────────────────────────────────────────────────┘
                       │ REST     │ WSS
                       ▼          ▼
            gamma-api.polymarket.com    wss-subscriptions-clob…
            clob.polymarket.com
```

Single asyncio process. Three layers (Telegram bot · alert engine · Polymarket client) sharing one SQLite database. All ticks flow through a single consumer task to prevent double-fire races.

See [`docs/design.md`](docs/design.md) for the full design spec and [`docs/plan.md`](docs/plan.md) for the implementation plan that produced the current codebase.

## Quick start (development)

Requirements: Python 3.12+, a Telegram bot token from [@BotFather](https://t.me/BotFather).

```bash
git clone https://github.com/<you>/polyalert.git
cd polyalert
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env       # paste your TELEGRAM_BOT_TOKEN
chmod 600 .env
python -m polyalert
```

Then message your bot — first `/start`, then a Polymarket event URL.

### Tests

```bash
pytest              # 62 tests across REST, WSS, engine, DB, FSM bits
ruff check src/ tests/
```

### End-to-end smoke against real Polymarket

```bash
# Single market: parses URL, fetches event, prices, opens WSS, waits for a tick.
PYTHONPATH=src python scripts/smoke_e2e.py 'polymarket.com/event/<your-event-slug>'

# Multi-market: verifies the batched-subscribe protocol with two distinct assets.
PYTHONPATH=src python scripts/smoke_multi.py <event-a-slug> <event-b-slug>
```

## Production deploy (Linux VPS, systemd)

```bash
# As root:
useradd -r -m -d /opt/polyalert -s /bin/bash polyalert
sudo -u polyalert git clone https://github.com/<you>/polyalert.git /opt/polyalert
cd /opt/polyalert
sudo -u polyalert python3.12 -m venv .venv
sudo -u polyalert .venv/bin/pip install -e .

sudo -u polyalert cp .env.example .env
sudo -u polyalert vim .env       # set TELEGRAM_BOT_TOKEN at minimum
chmod 600 .env
chown polyalert:polyalert .env

cp systemd/polyalert.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now polyalert
journalctl -u polyalert -f
```

### Daily SQLite backup

Add to root's crontab (`crontab -e`):

```cron
0 4 * * * sqlite3 /opt/polyalert/polyalert.db ".backup /opt/polyalert/backups/polyalert.db.$(date +\%F).bak" && find /opt/polyalert/backups -name 'polyalert.db.*.bak' -mtime +7 -delete
```

`sqlite3 .backup` is WAL-safe; plain `cp` is not.

## Configuration

All settings via `.env` (loaded by `pydantic-settings`):

| Var | Default | What |
|-----|---------|------|
| `TELEGRAM_BOT_TOKEN` | _(required)_ | From @BotFather |
| `POLYMARKET_REST_URL` | `https://gamma-api.polymarket.com` | Markets + events |
| `POLYMARKET_CLOB_URL` | `https://clob.polymarket.com` | Prices |
| `POLYMARKET_WSS_URL` | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | Real-time book |
| `DB_PATH` | `./polyalert.db` | SQLite file |
| `MAX_ALERTS_PER_USER` | `10` | Per-Telegram-user limit |
| `WSS_STALE_TIMEOUT_SECONDS` | `300` | Force reconnect after this much silence |
| `OWNER_USER_ID` | _(optional)_ | Telegram user_id allowed to run `/status` |
| `LOG_LEVEL` | `INFO` | Standard `logging` levels |

## Tech stack

Python 3.12 · asyncio · [aiogram 3](https://github.com/aiogram/aiogram) · [aiosqlite](https://github.com/omnilib/aiosqlite) · [httpx](https://github.com/encode/httpx) · [websockets](https://github.com/python-websockets/websockets) · [pydantic-settings](https://github.com/pydantic/pydantic-settings) · [pytest](https://github.com/pytest-dev/pytest) · [ruff](https://github.com/astral-sh/ruff).

## License

[MIT](LICENSE) — do what you like, no warranty.

## Disclaimer

This project is not affiliated with Polymarket. It uses Polymarket's public CLOB and gamma APIs as a consumer. API contracts can change without notice; if they do, open an issue (or a PR).
