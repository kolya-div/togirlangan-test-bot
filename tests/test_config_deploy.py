"""Railway uchun sozlamalar: DATABASE_URL formati, PORT, WebApp manzili."""

import pytest

from app.config import Settings

BASE = {"bot_token": "123456:ABC", "admin_ids": "1"}


@pytest.mark.parametrize("url", [
    "postgresql://u:p@host:5432/db",
    "postgres://u:p@host:5432/db",
    "postgresql+asyncpg://u:p@host:5432/db",
])
def test_database_url_accepts_railway_format(url):
    s = Settings(**BASE, database_url=url)
    assert s.database_url == "postgresql+asyncpg://u:p@host:5432/db"


def test_database_url_sslmode_converted_for_asyncpg():
    s = Settings(**BASE, database_url="postgresql://u:p@h/db?sslmode=require")
    assert s.database_url == "postgresql+asyncpg://u:p@h/db?ssl=require"


def test_unsupported_database_rejected():
    with pytest.raises(ValueError):
        Settings(**BASE, database_url="mysql://u:p@h/db")


@pytest.mark.parametrize("url,expected", [
    ("sqlite:///./data/bot.db", "sqlite+aiosqlite:///./data/bot.db"),
    ("sqlite+aiosqlite:///./data/bot.db", "sqlite+aiosqlite:///./data/bot.db"),
    ("", "sqlite+aiosqlite:///./data/bot.db"),  # bo'sh → standart SQLite
])
def test_sqlite_accepted(url, expected):
    assert Settings(**BASE, database_url=url).database_url == expected


def test_webapp_url_from_railway_domain(monkeypatch):
    monkeypatch.delenv("WEBAPP_URL", raising=False)
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "bot.up.railway.app")
    assert Settings(**BASE, _env_file=None).webapp_url == "https://bot.up.railway.app"


def test_explicit_webapp_url_wins(monkeypatch):
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "bot.up.railway.app")
    s = Settings(**BASE, webapp_url="https://test.example.uz/", _env_file=None)
    assert s.webapp_url == "https://test.example.uz"


def test_local_default_and_port_from_env(monkeypatch):
    monkeypatch.delenv("WEBAPP_URL", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)
    monkeypatch.setenv("PORT", "8123")
    s = Settings(**BASE, _env_file=None)
    assert s.port == 8123
    assert s.webapp_url == "http://localhost:8123"
