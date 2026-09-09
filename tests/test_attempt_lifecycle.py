"""
Attempt lifecycle testlari:
- Birinchi marta test boshlash
- Active test bilan qayta kirish
- Finished test bilan qayta kirish
- Finished attemptga answer yuborish
- Processing attemptga answer yuborish
- Finish endpoint ikki marta
- Results authorization
"""

import io
import hashlib
import hmac
import json
import time
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from datetime import datetime
from unittest.mock import patch

from unittest.mock import patch

from app.database.database import Base
from app.database.models import User, TestAttempt, Question
from app.database.repositories import (
    create_or_update_test_settings,
    get_user_attempt_count_today,
)
from app.main import app
from app.config import settings


def make_init_data(user_id: int, *, tamper_fields: dict | None = None) -> str:
    """Telegram WebApp initData strukturasida valid imzo yaratadi (test uchun).

    Telegramning rasmiy algoritmi:
      1. data_check_string = barcha `key=value` juftliklari (hash'dan
         tashqari) lexicographic tartibda, `\\n` bilan birlashtiriladi.
      2. secret_key = HMAC_SHA256(key=b"WebAppData", msg=bot_token)
      3. hash = HMAC_SHA256(key=secret_key, msg=data_check_string).hexdigest()

    `tamper_fields` berilsa — bu maydonlar imzolashdan OLDIN qo'shiladi
    (yoki asl qiymat buziladi), shuning uchun data_check_string o'zgaradi
    va backend uni rad etadi (negative test uchun).
    """
    user = {"id": user_id, "first_name": "Test", "username": "test_user"}
    params = {
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    if tamper_fields:
        params.update(tamper_fields)

    check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret_key = hmac.new(
        b"WebAppData",
        settings.bot_token.encode(),
        hashlib.sha256,
    ).digest()
    params["hash"] = hmac.new(
        secret_key,
        check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return "&".join(f"{k}={v}" for k, v in sorted(params.items()))



# ─── Test database (env dan olinadi yoki default PostgreSQL) ───
import os
from sqlalchemy.pool import NullPool
TEST_DB_URL = os.getenv(
    "TEST_DB_URL",
    "postgresql+asyncpg://postgres:123@localhost:5432/turkish_bot_test",
)
# NullPool: har ulanish yangi ochiladi — Windows'dagi loop birlashuvi
# ("attached to a different loop") xatosini oldini oladi.
test_engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_db():
    # ⚠️ XAVFSIZLIK HIMOYASI: drop_all hech qachon production DB'ga
    # tegmasligi uchun test engine DB nomi "_test" bilan tugashini talab
    # qilamiz. Aks holda (masalan TEST_DB_URL production'ga o'rnatilsa)
    # test darhol xato beradi, production ma'lumotlari o'chirilmaydi.
    db_name = TEST_DB_URL.split("?", 1)[0].rsplit("/", 1)[-1]
    if not db_name.endswith("_test"):
        raise RuntimeError(
            f"Xavfsizlik: TEST_DB_URL test bazasiga ishora qilmayapti "
            f"(database='{db_name}'). Test DB nomi '_test' bilan tugashi "
            f"shart — production ma'lumotlarga drop_all qo'llanilmaydi."
        )

    # Har test bo'lishiga toza jadval: avval eski jadvalni o'chirib,
    # model asosida yangi (joriy ustunlar bilan) yaratamiz. Bu mavjud
    # jadvalga yangi ustun qo'shilmagan (eski run'dan qolgan) holatini
    # yo'q qiladi.
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def mock_session():
    """Routes dagi SessionLocal ni test DB ga almashtirish."""
    with patch("app.api.routes.SessionLocal", TestSessionLocal):
        yield


async def _create_user(session: AsyncSession, telegram_id: int = 12345) -> User:
    user = User(telegram_id=telegram_id, is_registered=True)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _create_question(session: AsyncSession) -> Question:
    q = Question(
        section="A",
        order_number=1,
        text="Test savoli?",
        preparation_seconds=10,
        answer_seconds=30,
    )
    session.add(q)
    await session.commit()
    await session.refresh(q)
    return q


# ═══════════════════════════════════════════════
# Test 1 — Birinchi marta test boshlash
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_first_attempt_creates_active():
    async with TestSessionLocal() as session:
        await _create_user(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/attempts", data={"init_data": make_init_data(12345)})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["existing"] is False


# ═══════════════════════════════════════════════
# Test 2 — Active test bilan qayta kirish TAQIQLANADI
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_active_attempt_reentry_blocked():
    """Faol attempt bor bo'lganda /api/attempts ga qayta kirish 403 bilan
    taqiqlanadi — kuniga bitta test, "Testni boshlash" tugmasi faqat bir
    marta ishlatilishi kerak (design bo'yicha).
    """
    async with TestSessionLocal() as session:
        await _create_user(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp1 = await client.post("/api/attempts", data={"init_data": make_init_data(12345)})
        assert resp1.json()["existing"] is False

        resp2 = await client.post("/api/attempts", data={"init_data": make_init_data(12345)})
        assert resp2.status_code == 403


# ═══════════════════════════════════════════════
# Test 3 — Finished test bilan qayta kirish
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_finished_attempt_blocks_new():
    async with TestSessionLocal() as session:
        user = await _create_user(session)
        attempt = TestAttempt(user_id=user.id, status="finished", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/attempts", data={"init_data": make_init_data(12345)})

    assert resp.status_code == 403
    data = resp.json()
    assert "allaqachon" in data["detail"]["message"]


# ═══════════════════════════════════════════════
# Test 4 — Finished attemptga answer yuborish
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_answer_to_finished_attempt_403():
    async with TestSessionLocal() as session:
        user = await _create_user(session)
        q = await _create_question(session)
        attempt = TestAttempt(user_id=user.id, status="finished", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dummy_audio = io.BytesIO(b"x" * 4096)
        resp = await client.post(
            f"/api/attempts/{attempt_id}/answers/{q.id}",
            data={"init_data": make_init_data(12345)},
            files={"audio": ("test.webm", dummy_audio, "audio/webm")},
        )

    assert resp.status_code == 403
    assert "yakunlangan" in resp.json()["detail"]


# ═══════════════════════════════════════════════
# Test 5 — Processing attemptga answer yuborish
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_answer_to_processing_attempt_403():
    async with TestSessionLocal() as session:
        user = await _create_user(session)
        q = await _create_question(session)
        attempt = TestAttempt(user_id=user.id, status="processing", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dummy_audio = io.BytesIO(b"x" * 4096)
        resp = await client.post(
            f"/api/attempts/{attempt_id}/answers/{q.id}",
            data={"init_data": make_init_data(12345)},
            files={"audio": ("test.webm", dummy_audio, "audio/webm")},
        )

    assert resp.status_code == 403


# ═══════════════════════════════════════════════
# Test 6 — Finish endpoint ikki marta
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_finish_twice_second_409():
    async with TestSessionLocal() as session:
        user = await _create_user(session)
        attempt = TestAttempt(user_id=user.id, status="active", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp1 = await client.post(
            f"/api/attempts/{attempt_id}/finish",
            data={"init_data": make_init_data(12345)}
        )
        assert resp1.status_code == 200
        assert resp1.json()["processing"] is True

        resp2 = await client.post(
            f"/api/attempts/{attempt_id}/finish",
            data={"init_data": make_init_data(12345)}
        )
        assert resp2.status_code == 409
        assert "qayta ishlanmoqda" in resp2.json()["detail"]


@pytest.mark.anyio
async def test_finish_while_processing_409():
    async with TestSessionLocal() as session:
        user = await _create_user(session)
        attempt = TestAttempt(user_id=user.id, status="processing", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/attempts/{attempt_id}/finish",
            data={"init_data": make_init_data(12345)}
        )
        assert resp.status_code == 409
        assert "qayta ishlanmoqda" in resp.json()["detail"]


# ═══════════════════════════════════════════════
# Test 7 — Active attemptga answer yuborish (muvaffaqiyatli)
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_answer_to_active_attempt_works():
    async with TestSessionLocal() as session:
        user = await _create_user(session)
        q = await _create_question(session)
        attempt = TestAttempt(user_id=user.id, status="active", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dummy_audio = io.BytesIO(b"x" * 4096)
        resp = await client.post(
            f"/api/attempts/{attempt_id}/answers/{q.id}",
            data={"init_data": make_init_data(12345)},
            files={"audio": ("test.webm", dummy_audio, "audio/webm")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "filename" in data


# ═══════════════════════════════════════════════
# Test 12 — Question ID validation
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_answer_to_nonexistent_question_404():
    async with TestSessionLocal() as session:
        user = await _create_user(session)
        attempt = TestAttempt(user_id=user.id, status="active", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dummy_audio = io.BytesIO(b"x" * 4096)
        # Mavjud bo'lmagan question_id (99999)
        resp = await client.post(
            f"/api/attempts/{attempt_id}/answers/99999",
            data={"init_data": make_init_data(12345)},
            files={"audio": ("test.webm", dummy_audio, "audio/webm")},
        )

    assert resp.status_code == 404
    assert "Savol topilmadi" in resp.json()["detail"]


# ═══════════════════════════════════════════════
# Test 13 — Duplicate answer prevention
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_duplicate_answer_to_same_question_idempotent():
    async with TestSessionLocal() as session:
        user = await _create_user(session)
        q = await _create_question(session)
        attempt = TestAttempt(user_id=user.id, status="active", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dummy_audio = io.BytesIO(b"x" * 4096)

        # Birinchi answer
        resp1 = await client.post(
            f"/api/attempts/{attempt_id}/answers/{q.id}",
            data={"init_data": make_init_data(12345)},
            files={"audio": ("test.webm", dummy_audio, "audio/webm")},
        )
        assert resp1.status_code == 200
        assert resp1.json()["existing"] is False

        # Ikkinchi answer (bir xil question) — idempotent, 200 + existing
        resp2 = await client.post(
            f"/api/attempts/{attempt_id}/answers/{q.id}",
            data={"init_data": make_init_data(12345)},
            files={"audio": ("test.webm", dummy_audio, "audio/webm")},
        )

    assert resp2.status_code == 200
    assert resp2.json()["existing"] is True
    assert resp2.json()["filename"] == resp1.json()["filename"]


# ═══════════════════════════════════════════════
# Test 14 — Audio validation
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_answer_invalid_format_400():
    async with TestSessionLocal() as session:
        user = await _create_user(session)
        q = await _create_question(session)
        attempt = TestAttempt(user_id=user.id, status="active", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dummy_audio = io.BytesIO(b"x" * 4096)
        # Noto'g'ri format (.exe)
        resp = await client.post(
            f"/api/attempts/{attempt_id}/answers/{q.id}",
            data={"init_data": make_init_data(12345)},
            files={"audio": ("test.exe", dummy_audio, "application/octet-stream")},
        )

    assert resp.status_code == 400
    assert "formati qo'llab-quvvatlanmaydi" in resp.json()["detail"]


@pytest.mark.anyio
async def test_answer_too_large_413():
    async with TestSessionLocal() as session:
        user = await _create_user(session)
        q = await _create_question(session)
        attempt = TestAttempt(user_id=user.id, status="active", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Juda katta fayl (100MB)
        large_audio = io.BytesIO(b"x" * (100 * 1024 * 1024))
        resp = await client.post(
            f"/api/attempts/{attempt_id}/answers/{q.id}",
            data={"init_data": make_init_data(12345)},
            files={"audio": ("test.webm", large_audio, "audio/webm")},
        )

    assert resp.status_code == 413
    assert "juda katta" in resp.json()["detail"]


@pytest.mark.anyio
async def test_answer_too_small_400():
    async with TestSessionLocal() as session:
        user = await _create_user(session)
        q = await _create_question(session)
        attempt = TestAttempt(user_id=user.id, status="active", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Juda kichik fayl (100 bytes)
        small_audio = io.BytesIO(b"x" * 100)
        resp = await client.post(
            f"/api/attempts/{attempt_id}/answers/{q.id}",
            data={"init_data": make_init_data(12345)},
            files={"audio": ("test.webm", small_audio, "audio/webm")},
        )

    assert resp.status_code == 400
    assert "juda kichik" in resp.json()["detail"]


# ═══════════════════════════════════════════════
# Test 8 — Results endpoint
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_results_own_attempt():
    async with TestSessionLocal() as session:
        user = await _create_user(session, telegram_id=111)
        attempt = TestAttempt(user_id=user.id, status="finished", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/attempts/{attempt_id}/results",
            params={"init_data": make_init_data(111)}
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["attempt_id"] == attempt_id
    assert data["status"] == "finished"


@pytest.mark.anyio
async def test_results_nonexistent_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/attempts/99999/results",
            params={"init_data": make_init_data(111)}
        )

    assert resp.status_code == 404


@pytest.mark.anyio
async def test_results_unauthorized_401():
    async with TestSessionLocal() as session:
        user = await _create_user(session, telegram_id=111)
        attempt = TestAttempt(user_id=user.id, status="finished", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/attempts/{attempt_id}/results",
            params={"init_data": "invalid_init_data"}
        )

    assert resp.status_code == 401


@pytest.mark.anyio
async def test_results_wrong_user_403():
    async with TestSessionLocal() as session:
        user = await _create_user(session, telegram_id=111)
        attempt = TestAttempt(user_id=user.id, status="finished", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Boshqa user ID (222) bilan urinib ko'ramiz
        resp = await client.get(
            f"/api/attempts/{attempt_id}/results",
            params={"init_data": make_init_data(222)}
        )

    assert resp.status_code == 403
    assert "tegishli emas" in resp.json()["detail"]


# ═══════════════════════════════════════════════
# Test 9 — Status transitionlari
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_active_to_processing_on_finish():
    with patch("app.api.routes.enqueue_report"):
        async with TestSessionLocal() as session:
            user = await _create_user(session)
            attempt = TestAttempt(user_id=user.id, status="active", started_at=datetime.utcnow())
            session.add(attempt)
            await session.commit()
            await session.refresh(attempt)
            attempt_id = attempt.id

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/attempts/{attempt_id}/finish",
                data={"init_data": make_init_data(12345)}
            )
            assert resp.status_code == 200

        async with TestSessionLocal() as session:
            from sqlalchemy import select
            a = (await session.execute(
                select(TestAttempt).where(TestAttempt.id == attempt_id)
            )).scalar_one()
            assert a.status == "processing"


# ═══════════════════════════════════════════════
# Test 10 — Answer upload authorization
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_answer_upload_unauthorized_401():
    async with TestSessionLocal() as session:
        user = await _create_user(session)
        q = await _create_question(session)
        attempt = TestAttempt(user_id=user.id, status="active", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dummy_audio = io.BytesIO(b"x" * 4096)
        resp = await client.post(
            f"/api/attempts/{attempt_id}/answers/{q.id}",
            data={"init_data": "invalid_init_data"},
            files={"audio": ("test.webm", dummy_audio, "audio/webm")},
        )

    assert resp.status_code == 401


@pytest.mark.anyio
async def test_answer_upload_wrong_user_403():
    async with TestSessionLocal() as session:
        user = await _create_user(session, telegram_id=111)
        q = await _create_question(session)
        attempt = TestAttempt(user_id=user.id, status="active", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dummy_audio = io.BytesIO(b"x" * 4096)
        # Boshqa user ID (222) bilan urinib ko'ramiz
        resp = await client.post(
            f"/api/attempts/{attempt_id}/answers/{q.id}",
            data={"init_data": make_init_data(222)},
            files={"audio": ("test.webm", dummy_audio, "audio/webm")},
        )

    assert resp.status_code == 403
    assert "tegishli emas" in resp.json()["detail"]


# ═══════════════════════════════════════════════
# Test 11 — Finish endpoint authorization
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_finish_unauthorized_401():
    async with TestSessionLocal() as session:
        user = await _create_user(session)
        attempt = TestAttempt(user_id=user.id, status="active", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/attempts/{attempt_id}/finish",
            data={"init_data": "invalid_init_data"}
        )

    assert resp.status_code == 401


@pytest.mark.anyio
async def test_finish_wrong_user_403():
    async with TestSessionLocal() as session:
        user = await _create_user(session, telegram_id=111)
        attempt = TestAttempt(user_id=user.id, status="active", started_at=datetime.utcnow())
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Boshqa user ID (222) bilan urinib ko'ramiz
        resp = await client.post(
            f"/api/attempts/{attempt_id}/finish",
            data={"init_data": make_init_data(222)}
        )

    assert resp.status_code == 403
    assert "tegishli emas" in resp.json()["detail"]


# ═══════════════════════════════════════════════
# Test 11 — PostgreSQL da sanani taqqoslash (cast(Date))
#   repositories dagi func.date(...) -> .cast(Date) tuzatishi.
#   SQLite'ga xos `date(col)` funksiyasi Postgres'da yo'q — agar tuzatish
#   bo'lmasa bu test "function date() does not exist" bilan yiqiladi.
# ═══════════════════════════════════════════════
async def _create_attempt(session, user, started_at):
    attempt = TestAttempt(
        user_id=user.id,
        status="finished",
        started_at=started_at,
    )
    session.add(attempt)
    await session.commit()
    return attempt


@pytest.mark.anyio
async def test_get_user_attempt_count_today_uses_cast_date():
    async with TestSessionLocal() as session:
        user = await _create_user(session, telegram_id=555011)

        # Bugungi sana bilan 2 ta attempt (count = 2)
        await _create_attempt(session, user, datetime.utcnow())
        await _create_attempt(session, user, datetime.utcnow())

        # Har qanday attempt yaratildi — funksiya xato bermasligi kerak
        count = await get_user_attempt_count_today(session, user.id)

    assert count == 2


@pytest.mark.anyio
async def test_create_or_update_test_settings_uses_cast_date():
    async with TestSessionLocal() as session:
        s = await create_or_update_test_settings(session, test_mode="daily", vip_limit=3)

    assert s.test_mode == "daily"
    assert s.vip_limit == 3
    assert s.id is not None

    # Yangilash — yangi qator yaratilmasligi, mavjudi yangilanishi kerak
    async with TestSessionLocal() as session:
        s2 = await create_or_update_test_settings(session, test_mode="vip", vip_limit=5)

    assert s2.test_mode == "vip"
    assert s2.vip_limit == 5
    assert s2.id == s.id
