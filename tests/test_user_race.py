"""Bir xil foydalanuvchining bir nechta /start'i bir vaqtda kelsa (bot qayta
ishga tushgach to'planib qolgan xabarlar) — UniqueViolation bilan yiqilmaydi,
hammasi bitta userni qaytaradi."""

import asyncio
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database.database import Base
from app.database.models import User
from app.database.repositories import get_or_create_user

TEST_DB_URL = os.getenv(
    "TEST_DB_URL",
    "postgresql+asyncpg://postgres:123@localhost:5432/turkish_bot_test",
)
test_engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_db():
    db_name = TEST_DB_URL.split("?", 1)[0].rsplit("/", 1)[-1]
    if not db_name.endswith("_test"):
        raise RuntimeError(f"Xavfsizlik: TEST_DB_URL test bazasi emas ({db_name})")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.anyio
async def test_concurrent_start_does_not_crash():
    tg_id = 860103732

    async def one_start():
        async with TestSessionLocal() as session:
            user = await get_or_create_user(session, tg_id, "u", "Ism", admin_ids=[])
            return user.id

    ids = await asyncio.gather(*(one_start() for _ in range(5)))

    assert len(set(ids)) == 1
    async with TestSessionLocal() as s:
        count = (await s.execute(
            select(func.count()).select_from(User).where(User.telegram_id == tg_id)
        )).scalar()
    assert count == 1
