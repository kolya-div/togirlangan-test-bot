"""
AI hamma javoblarni tekshirib bo'lgach Word + Excel adminlarga avtomatik:
- bir nechta test ketma-ket baholansa — bitta hisobot (debounce)
- hali tekshirilayotgan test bo'lsa — kutadi, keyin yuboradi
- hisobot matni va ikkala fayl adminga boradi, fayllar o'chiriladi
"""

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.database.database import Base
from app.database.models import TestAttempt, User
from app.services import auto_report

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
    auto_report.mark_reported()
    with patch.object(settings, "auto_report_delay_seconds", 0.2), \
         patch("app.database.database.SessionLocal", TestSessionLocal):
        yield
    await auto_report.stop()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.anyio
async def test_many_evaluations_send_one_report():
    send = AsyncMock(return_value=True)
    with patch.object(auto_report, "_all_evaluated", AsyncMock(return_value=True)), \
         patch.object(auto_report, "send_auto_report", send):
        for _ in range(5):
            auto_report.notify_attempt_evaluated()
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)
    send.assert_awaited_once()


@pytest.mark.anyio
async def test_waits_while_attempts_still_processing():
    send = AsyncMock(return_value=True)
    done = AsyncMock(side_effect=[False, False, True])
    with patch.object(auto_report, "_all_evaluated", done), \
         patch.object(auto_report, "send_auto_report", send):
        auto_report.notify_attempt_evaluated()
        await asyncio.sleep(0.3)
        send.assert_not_awaited()  # hali "processing" bor
        await asyncio.sleep(0.6)
    send.assert_awaited_once()
    assert done.await_count == 3


@pytest.mark.anyio
async def test_send_auto_report_sends_both_files_to_admins(tmp_path):
    async with TestSessionLocal() as s:
        u1 = User(telegram_id=1, full_name="Ali", is_registered=True)
        u2 = User(telegram_id=2, full_name="Vali", is_registered=True)
        s.add_all([u1, u2])
        await s.flush()
        s.add_all([
            TestAttempt(user_id=u1.id, status="finished", score=50, level="B1"),
            TestAttempt(user_id=u2.id, status="active"),
        ])
        await s.commit()

    from app.services.telegram_sender import telegram_sender
    sent_files = []

    async def fake_send_document(chat_id, document_path, caption=""):
        assert document_path.exists()
        sent_files.append(document_path)
        return True

    auto_report.notify_attempt_evaluated()
    await auto_report.stop()  # taymerni o'chirib, qo'lda yuboramiz
    with patch("app.services.daily_export_wipe.async_session", TestSessionLocal), \
         patch.object(telegram_sender, "send_document", side_effect=fake_send_document), \
         patch.object(telegram_sender, "send_message", AsyncMock(return_value=True)) as msg:
        assert await auto_report.send_auto_report() is True

    text = msg.await_args.kwargs["text"]
    assert "Tekshirilgan testlar: <b>1</b>" in text
    assert "Hali tugatmaganlar: <b>1</b>" in text
    assert sorted(p.suffix for p in sent_files) == [".docx", ".xlsx"]
    assert not any(p.exists() for p in sent_files)  # yuborilgach o'chirildi

    # Yangi natija bo'lmasa qayta yuborilmaydi
    assert await auto_report.send_auto_report() is False
