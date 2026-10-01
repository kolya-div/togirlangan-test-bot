"""
Tiqilib qolgan "processing" attemptlarni tiklash va test holatini
ishga tushishda DB dan yuklash testlari:
- Stuck processing attempt qayta navbatga qo'yiladi (holat "processing" qoladi)
- Navbatdagi (pending) attempt qayta qo'shilmaydi
- Yangi (stale chegarasidan yosh) attempt tegilmaydi
- MAX_REQUEUE_ATTEMPTS dan keyin qayta qo'shilmaydi, admin bir marta xabardor qilinadi
- load_test_state_from_db test holati va invite tokenni tiklaydi
"""

import os
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.bot import test_state
from app.database.database import Base
from app.database.models import TestAttempt, User
from app.database.models import TestSettings as SettingsRow
from app.services import cleanup_service, report_worker
from app.utils.helpers import utcnow

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
    cleanup_service._requeue_counts.clear()
    report_worker._pending_attempts.clear()
    yield
    report_worker._pending_attempts.clear()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


_next_tg_id = iter(range(555000, 556000))


async def _create_attempt(status: str, finished_minutes_ago: int) -> int:
    async with TestSessionLocal() as session:
        user = User(telegram_id=next(_next_tg_id), is_registered=True)
        session.add(user)
        await session.flush()
        attempt = TestAttempt(
            user_id=user.id,
            status=status,
            started_at=utcnow() - timedelta(minutes=finished_minutes_ago + 10),
            finished_at=utcnow() - timedelta(minutes=finished_minutes_ago),
        )
        session.add(attempt)
        await session.commit()
        return attempt.id


async def _status(attempt_id: int) -> str:
    async with TestSessionLocal() as session:
        return (await session.get(TestAttempt, attempt_id)).status


@pytest.mark.anyio
async def test_stuck_processing_is_requeued_not_reset():
    attempt_id = await _create_attempt("processing", finished_minutes_ago=60)

    with patch.object(report_worker, "enqueue_report", AsyncMock(return_value=True)) as enq:
        async with TestSessionLocal() as session:
            count = await cleanup_service.requeue_stuck_processing(session)

    assert count == 1
    enq.assert_awaited_once_with(attempt_id, total_answers=0)
    # Holat "active" ga qaytmaydi — aks holda user bloklanib qolardi.
    assert await _status(attempt_id) == "processing"


@pytest.mark.anyio
async def test_pending_attempt_is_not_requeued():
    attempt_id = await _create_attempt("processing", finished_minutes_ago=60)
    report_worker._pending_attempts.add(attempt_id)

    with patch.object(report_worker, "enqueue_report", AsyncMock(return_value=True)) as enq:
        async with TestSessionLocal() as session:
            count = await cleanup_service.requeue_stuck_processing(session)

    assert count == 0
    enq.assert_not_awaited()


@pytest.mark.anyio
async def test_fresh_processing_untouched_unless_startup():
    attempt_id = await _create_attempt("processing", finished_minutes_ago=1)
    await _create_attempt("finished", finished_minutes_ago=60)
    await _create_attempt("active", finished_minutes_ago=60)

    with patch.object(report_worker, "enqueue_report", AsyncMock(return_value=True)) as enq:
        async with TestSessionLocal() as session:
            assert await cleanup_service.requeue_stuck_processing(session) == 0
            enq.assert_not_awaited()

            # Startup: navbat bo'sh — barcha processing darhol qaytariladi.
            assert await cleanup_service.requeue_stuck_processing(session, stale_minutes=0) == 1
            enq.assert_awaited_once_with(attempt_id, total_answers=0)


@pytest.mark.anyio
async def test_requeue_limit_notifies_admins_once():
    attempt_id = await _create_attempt("processing", finished_minutes_ago=60)
    notify = AsyncMock()

    with patch.object(report_worker, "enqueue_report", AsyncMock(return_value=True)) as enq, \
         patch.object(cleanup_service, "_notify_admins_requeue_limit", notify):
        for _ in range(cleanup_service.MAX_REQUEUE_ATTEMPTS + 3):
            async with TestSessionLocal() as session:
                await cleanup_service.requeue_stuck_processing(session)

    assert enq.await_count == cleanup_service.MAX_REQUEUE_ATTEMPTS
    notify.assert_awaited_once_with([attempt_id])


@pytest.mark.anyio
async def test_load_test_state_from_db_restores_cache():
    async with TestSessionLocal() as session:
        session.add(SettingsRow(is_active=True, invite_token="tok123", date=utcnow()))
        await session.commit()

    test_state.set_test_active_cache(False)
    test_state._invite_token_cache = None
    try:
        with patch("app.database.database.SessionLocal", TestSessionLocal):
            await test_state.load_test_state_from_db()
        assert test_state.is_test_active() is True
        assert test_state.get_invite_token() == "tok123"
    finally:
        test_state.set_test_active_cache(False)
        test_state._invite_token_cache = None


@pytest.mark.anyio
async def test_orphan_cleanup_keeps_question_images(tmp_path):
    """Savol rasmlari (data/audios/images) 'yetim audio' deb o'chirilmasin."""
    import time as _time

    images = tmp_path / "images"
    images.mkdir()
    img = images / "rId4.png"
    img.write_bytes(b"png")
    orphan = tmp_path / "7" / "old.webm"
    orphan.parent.mkdir()
    orphan.write_bytes(b"audio")
    old = _time.time() - 3600  # 1 soat oldin — ORPHAN_MIN_AGE dan eski
    os.utime(img, (old, old))
    os.utime(orphan, (old, old))

    with patch.object(cleanup_service.settings, "upload_dir", str(tmp_path)):
        async with TestSessionLocal() as session:
            deleted = await cleanup_service.delete_orphan_audios(session)

    assert img.exists(), "savol rasmi o'chirilmasligi kerak"
    assert not orphan.exists(), "haqiqiy yetim audio o'chirilishi kerak"
    assert deleted == 1
