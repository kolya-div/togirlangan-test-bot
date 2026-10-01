"""
Natijalar foydalanuvchiga ko'rsatilmaydi — faqat admin .docx hisobotida:
- /results foydalanuvchiga faqat holatni qaytaradi (ball/xatolar yo'q), admin to'liq oladi
- /status foydalanuvchiga ball/darajani qaytarmaydi
- Baholashdan keyin foydalanuvchiga Telegram'da hech narsa yuborilmaydi,
  lekin ball bazaga yoziladi (hisobot uchun)
- Test yakunlanganda "qabul qilindi" xabari boradi (natija va'da qilinmaydi)
"""

import hashlib
import hmac
import json
import os
import time
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import routes
from app.config import settings
from app.database.database import Base
from app.database.models import Answer, Question, TestAttempt, User
from app.main import app
from app.services import report_service

TEST_DB_URL = os.getenv(
    "TEST_DB_URL",
    "postgresql+asyncpg://postgres:123@localhost:5432/turkish_bot_test",
)
test_engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

USER_TG = 555111
ADMIN_TG = settings.admin_id_list[0]


def make_init_data(user_id: int) -> str:
    params = {
        "user": json.dumps({"id": user_id, "first_name": "T"}, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    check = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return "&".join(f"{k}={v}" for k, v in sorted(params.items()))


@pytest.fixture(autouse=True)
async def setup_db():
    db_name = TEST_DB_URL.split("?", 1)[0].rsplit("/", 1)[-1]
    if not db_name.endswith("_test"):
        raise RuntimeError(f"Xavfsizlik: TEST_DB_URL test bazasi emas ({db_name})")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    with patch.object(routes, "SessionLocal", TestSessionLocal), \
         patch.object(report_service, "SessionLocal", TestSessionLocal):
        yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _finished_attempt(telegram_id: int) -> int:
    async with TestSessionLocal() as s:
        user = User(telegram_id=telegram_id, is_registered=True)
        q = Question(section="1.1", order_number=1, text="Soru?", max_points=10)
        s.add_all([user, q])
        await s.flush()
        attempt = TestAttempt(user_id=user.id, status="finished", score=50, level="B1")
        s.add(attempt)
        await s.flush()
        s.add(Answer(attempt_id=attempt.id, question_id=q.id, score=80, transcript="Merhaba",
                     feedback=json.dumps({"mistakes": [{"original": "a", "correct": "b"}]})))
        await s.commit()
        return attempt.id


async def _get(path: str, telegram_id: int):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path, params={"init_data": make_init_data(telegram_id)})


@pytest.mark.anyio
async def test_user_gets_only_status_from_results():
    aid = await _finished_attempt(USER_TG)
    resp = await _get(f"/api/attempts/{aid}/results", USER_TG)
    assert resp.status_code == 200
    assert resp.json() == {"attempt_id": aid, "status": "finished"}


@pytest.mark.anyio
async def test_admin_still_gets_full_results():
    aid = await _finished_attempt(ADMIN_TG)
    resp = await _get(f"/api/attempts/{aid}/results", ADMIN_TG)
    data = resp.json()
    assert data["total_score"] == 50
    assert data["results"][0]["mistakes"]


@pytest.mark.anyio
async def test_status_hides_score_from_user():
    aid = await _finished_attempt(USER_TG)
    data = (await _get(f"/api/attempts/{aid}/status", USER_TG)).json()
    assert data["status"] == "completed"
    assert "score" not in data and "level" not in data


@pytest.mark.anyio
async def test_report_processing_sends_nothing_to_user_but_saves_score():
    async with TestSessionLocal() as s:
        user = User(telegram_id=USER_TG, is_registered=True)
        q = Question(section="1.1", order_number=1, text="Soru?", max_points=10)
        s.add_all([user, q])
        await s.flush()
        attempt = TestAttempt(user_id=user.id, status="processing")
        s.add(attempt)
        await s.flush()
        s.add(Answer(attempt_id=attempt.id, question_id=q.id, transcript="Merhaba dünya"))
        await s.commit()
        aid = attempt.id

    evaluation = {"score": 80, "level": "B2", "mistakes": [], "strengths": [],
                  "feedback_uz": "", "feedback_tr": ""}
    from app.services.telegram_sender import telegram_sender
    with patch.object(report_service, "evaluate_answer", AsyncMock(return_value=evaluation)), \
         patch.object(telegram_sender, "send_message", AsyncMock()) as msg, \
         patch.object(telegram_sender, "send_audio", AsyncMock()) as audio:
        await report_service._process_attempt_and_report_inner(aid)

    msg.assert_not_awaited()
    audio.assert_not_awaited()
    async with TestSessionLocal() as s:
        attempt = await s.get(TestAttempt, aid)
    assert attempt.status == "finished"
    assert attempt.score == 60  # 80% × 10 ball → 8/10 → 60/75


@pytest.mark.anyio
async def test_finish_message_does_not_promise_results():
    async with TestSessionLocal() as s:
        user = User(telegram_id=USER_TG, is_registered=True)
        s.add(user)
        await s.flush()
        attempt = TestAttempt(user_id=user.id, status="active")
        s.add(attempt)
        await s.commit()
        aid = attempt.id

    with patch.object(routes, "_send_telegram", AsyncMock()) as send, \
         patch.object(routes, "enqueue_report", AsyncMock(return_value=True)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(f"/api/attempts/{aid}/finish",
                                data={"init_data": make_init_data(USER_TG)})

    assert resp.status_code == 200
    text = send.await_args.args[1]
    assert "qabul qilindi" in text
    assert "daqiqa" not in text and "yuboriladi" not in text
