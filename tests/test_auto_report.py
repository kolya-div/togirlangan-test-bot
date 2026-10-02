"""
AI hamma javoblarni tekshirib bo'lgach adminlardan so'raladi:
"Javoblar tayyor. Yana testdan o'tadiganlar bormi?" [Ha] [Yo'q]
- bir nechta test ketma-ket baholansa — bitta savol (debounce)
- hali tekshirilayotgan test bo'lsa — kutadi, keyin so'raydi
- yangi natija bo'lmasa qayta so'ralmaydi; admin javob bermagan bo'lsa ham
  yangi testlar tekshirilgach yana so'raladi
- xato bilan tugagan test ham savolni ishga tushiradi
- «Yo'q» → Word + Excel adminlarga, «Ha» → admin panel tugmalari
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
async def test_many_evaluations_ask_once():
    send = AsyncMock(return_value=1)
    with patch.object(auto_report, "_all_evaluated", AsyncMock(return_value=True)), \
         patch.object(auto_report, "ask_admins", send):
        for _ in range(5):
            auto_report.notify_attempt_evaluated()
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)
    send.assert_awaited_once()


@pytest.mark.anyio
async def test_waits_while_attempts_still_processing():
    send = AsyncMock(return_value=1)
    done = AsyncMock(side_effect=[False, False, True])
    with patch.object(auto_report, "_all_evaluated", done), \
         patch.object(auto_report, "ask_admins", send):
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
        assert await auto_report.send_auto_report(force=True) is True

    text = msg.await_args.kwargs["text"]
    assert "Tekshirilgan testlar: <b>1</b>" in text
    assert "Hali tugatmaganlar: <b>1</b>" in text
    assert sorted(p.suffix for p in sent_files) == [".docx", ".xlsx"]
    assert not any(p.exists() for p in sent_files)  # yuborilgach o'chirildi

    # Yangi natija bo'lmasa avtomatik qayta yuborilmaydi
    assert await auto_report.send_auto_report() is False


@pytest.mark.anyio
async def test_ask_admins_sends_yes_no_buttons_once():
    from app.bot.bot import bot

    with patch.object(bot, "send_message", AsyncMock()) as send:
        auto_report.notify_attempt_evaluated()
        await auto_report.stop()
        assert await auto_report.ask_admins() == 1
        # Yangi natija bo'lmasa qayta so'ralmaydi
        assert await auto_report.ask_admins() == 0

        text = send.await_args.args[1]
        kb = send.await_args.kwargs["reply_markup"].inline_keyboard
        assert "Barcha javoblar tayyor" in text
        assert "Yana testdan o'tadiganlar bormi?" in text
        assert [(b.text, b.callback_data) for b in kb[0]] == [
            ("✅ Ha", "autorep_yes"), ("❌ Yo'q", "autorep_no"),
        ]

        # «Ha» → keyingi testlar tekshirilgach yana so'raladi
        auto_report.answer_yes()
        auto_report.notify_attempt_evaluated()
        await auto_report.stop()
        assert await auto_report.ask_admins() == 1


def _callback(data: str, user_id: int):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    cb = MagicMock()
    cb.data = data
    cb.from_user = SimpleNamespace(id=user_id)
    cb.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    return cb


@pytest.mark.anyio
async def test_no_button_sends_results():
    from app.bot.handlers import admin

    cb = _callback("autorep_no", settings.admin_id_list[0])
    with patch.object(auto_report, "send_auto_report", AsyncMock(return_value=True)) as send:
        await admin.auto_report_no(cb)
    send.assert_awaited_once_with(force=True)
    cb.message.answer.assert_not_awaited()  # xato xabari yo'q


@pytest.mark.anyio
async def test_yes_button_shows_admin_menu():
    from app.bot.handlers import admin

    state = AsyncMock()
    cb = _callback("autorep_yes", settings.admin_id_list[0])
    with patch.object(auto_report, "answer_yes") as yes:
        await admin.auto_report_yes(cb, state)
    yes.assert_called_once()
    markup = cb.message.answer.await_args.kwargs["reply_markup"]
    datas = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "invite_link" in datas and "results" in datas


@pytest.mark.anyio
async def test_buttons_reject_non_admin():
    from app.bot.handlers import admin

    cb = _callback("autorep_no", 999)
    with patch.object(auto_report, "send_auto_report", AsyncMock()) as send:
        await admin.auto_report_no(cb)
    send.assert_not_awaited()


@pytest.mark.anyio
async def test_unanswered_prompt_does_not_block_next_one():
    # Admin birinchi savolga javob bermadi — keyingi testlar tekshirilgach
    # savol baribir yana chiqishi kerak (oldin chiqmay qolardi).
    from app.bot.bot import bot

    with patch.object(bot, "send_message", AsyncMock()):
        auto_report.notify_attempt_evaluated()
        await auto_report.stop()
        assert await auto_report.ask_admins() == 1

        auto_report.notify_attempt_evaluated()
        await auto_report.stop()
        assert await auto_report.ask_admins() == 1


@pytest.mark.anyio
async def test_stuck_processing_in_db_does_not_block_prompt():
    async with TestSessionLocal() as s:
        user = User(telegram_id=5, full_name="X", is_registered=True)
        s.add(user)
        await s.flush()
        s.add(TestAttempt(user_id=user.id, status="processing"))
        await s.commit()
    from app.services import report_worker

    # Navbat bo'sh (boshqa testlardan qolgan holat ta'sir qilmasin)
    with patch.object(report_worker, "_pending_attempts", set()), \
            patch.object(report_worker, "_report_queue", None):
        assert await auto_report._all_evaluated() is True


@pytest.mark.anyio
async def test_failed_attempt_still_triggers_prompt():
    from app.services import report_worker

    notify = patch.object(auto_report, "notify_attempt_evaluated")
    queue = asyncio.Queue()
    await queue.put(42)
    with notify as n, \
            patch.object(report_worker, "_ensure_queue", return_value=queue), \
            patch.object(report_worker, "_get_process_fn",
                         return_value=AsyncMock(side_effect=RuntimeError("AI xato"))), \
            patch.object(report_worker.job_tracker, "start_processing", AsyncMock()), \
            patch.object(report_worker.job_tracker, "fail", AsyncMock()):
        task = asyncio.create_task(report_worker._report_worker(0))
        await asyncio.wait_for(queue.join(), 2)
        task.cancel()
    n.assert_called_once()
