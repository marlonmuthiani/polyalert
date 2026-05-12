import pytest
from pydantic import ValidationError

from polyalert.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc:defghij")
    monkeypatch.setenv("DB_PATH", "/tmp/x.db")
    s = Settings(_env_file=None)
    assert s.telegram_bot_token == "abc:defghij"
    assert s.db_path == "/tmp/x.db"
    assert s.max_alerts_per_user == 10  # default
    assert s.polymarket_rest_url.startswith("https://")
    assert s.polymarket_wss_url.startswith("wss://")


def test_settings_requires_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
