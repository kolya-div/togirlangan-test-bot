"""Ishga tushishda baza ulanishi bir martalik uzilsa — qayta uriniladi."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.database import database


class _Conn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *_):
        return None


@pytest.mark.anyio
async def test_retries_then_succeeds():
    calls = {"n": 0}

    def connect():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionResetError("WinError 10054")
        return _Conn()

    fake_engine = MagicMock(connect=connect, dispose=AsyncMock())
    with patch.object(database, "engine", fake_engine), \
            patch.object(database.asyncio, "sleep", AsyncMock()) as sleep:
        await database._wait_for_database()

    assert calls["n"] == 3
    assert sleep.await_count == 2


@pytest.mark.anyio
async def test_gives_up_after_all_attempts():
    def connect():
        raise ConnectionResetError("WinError 10054")

    fake_engine = MagicMock(connect=connect, dispose=AsyncMock())
    with patch.object(database, "engine", fake_engine), \
            patch.object(database.asyncio, "sleep", AsyncMock()):
        with pytest.raises(ConnectionResetError):
            await database._wait_for_database()
