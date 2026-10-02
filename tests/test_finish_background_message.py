"""Test yakunlanganda foydalanuvchiga xabar fonda yuboriladi —
Telegram sekin bo'lsa ham /finish javobi kutib qolmaydi."""

import asyncio
import time

import pytest

from app.api import routes


@pytest.mark.anyio
async def test_send_in_background_does_not_block(monkeypatch):
    done = asyncio.Event()

    async def slow_send(*_):
        await asyncio.sleep(0.3)
        done.set()

    monkeypatch.setattr(routes, "_send_telegram", slow_send)
    t0 = time.monotonic()
    routes._send_in_background(1, "x")
    assert time.monotonic() - t0 < 0.05
    await asyncio.wait_for(done.wait(), 2)


@pytest.mark.anyio
async def test_send_in_background_swallows_errors(monkeypatch):
    async def failing_send(*_):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(routes, "_send_telegram", failing_send)
    routes._send_in_background(1, "x")
    await asyncio.sleep(0.05)
    assert not routes._background_tasks
