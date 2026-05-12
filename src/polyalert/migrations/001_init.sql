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
