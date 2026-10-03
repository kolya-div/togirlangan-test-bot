"""ADMIN_IDS o'zgartirilganda admin holati bazada ham yangilanadi."""

import os

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database.database import Base
from app.database.models import User
from app.database.repositories import get_or_create_user, sync_admin_flags

TEST_DB_URL = os.getenv(
    "TEST_DB_URL",
    "postgresql+asyncpg://postgres:123@localhost:5432/turkish_bot_test",
)
engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def db():
    assert TEST_DB_URL.split("?", 1)[0].rsplit("/", 1)[-1].endswith("_test")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _user(session, tg, admins):
    return await get_or_create_user(session, tg, None, "X", admin_ids=admins)


@pytest.mark.anyio
async def test_start_updates_admin_flag_when_admin_ids_change():
    async with Session() as s:
        assert (await _user(s, 111, [111])).is_admin is True
        assert (await _user(s, 222, [111])).is_admin is False

    # ADMIN_IDS: 111 → 222
    async with Session() as s:
        assert (await _user(s, 111, [222])).is_admin is False  # eski admin
        assert (await _user(s, 222, [222])).is_admin is True   # yangi admin


@pytest.mark.anyio
async def test_startup_sync_grants_and_revokes():
    async with Session() as s:
        s.add_all([
            User(telegram_id=111, full_name="old", is_admin=True),
            User(telegram_id=222, full_name="new", is_admin=False),
            User(telegram_id=333, full_name="user", is_admin=False),
        ])
        await s.commit()
        assert await sync_admin_flags(s, [222]) == 2
        rows = dict((await s.execute(select(User.telegram_id, User.is_admin))).all())
    assert rows == {111: False, 222: True, 333: False}
