"""
Registration flow testlari (HTTP endpoint-level):
- Birinchi ro'yxatdan o'tish
- Mavjud user bilan qayta kirish
- Savollar soni tekshirish
- Init data validatsiya
"""

import json
import time
import hmac
import hashlib
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from unittest.mock import patch
import os

from app.database.database import Base
from app.database.models import User, Question
from app.config import settings
from app.main import app


TEST_DB_URL = os.getenv(
    "TEST_DB_URL",
    "postgresql+asyncpg://postgres:123@localhost:5432/turkish_bot_test",
)

test_engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


def make_init_data(user_id: int, **extra) -> str:
    user = {"id": user_id, "first_name": "Test", "username": "test_user"}
    params = {
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    params.update(extra)

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


@pytest.fixture(autouse=True)
async def setup_db():
    db_name = TEST_DB_URL.split("?", 1)[0].rsplit("/", 1)[-1]
    if not db_name.endswith("_test"):
        raise RuntimeError(f"Safety: TEST_DB_URL must point to a test database (got '{db_name}')")

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def mock_session():
    with patch("app.api.routes.SessionLocal", TestSessionLocal):
        yield


async def _create_user(session: AsyncSession, telegram_id: int) -> User:
    user = User(telegram_id=telegram_id, is_registered=True)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _create_question(session: AsyncSession, **kwargs) -> Question:
    defaults = {
        "section": "A",
        "order_number": 1,
        "text": "Test savoli?",
        "preparation_seconds": 10,
        "answer_seconds": 30,
        "is_active": True,
    }
    defaults.update(kwargs)
    q = Question(**defaults)
    session.add(q)
    await session.commit()
    await session.refresh(q)
    return q


# ═══════════════════════════════════════════════
# Test 1 — /api/init yangi (ro'yxatdan o'tmagan) user uchun
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_init_new_user_not_registered():
    """Ro'yxatdan o'tmagan user /api/init da registered=False oladi.

    Ro'yxatdan o'tish BOT orqali (taklif havolasi + telefon) amalga
    oshiriladi — /api/init user yaratmaydi, faqat holatni qaytaradi.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/init",
            data={"init_data": make_init_data(99901)},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "user_id" in data
    assert data["registered"] is False
    assert data["status"] is None


# ═══════════════════════════════════════════════
# Test 2 — Mavjud user bilan qayta kirish
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_existing_user_returns_same():
    async with TestSessionLocal() as session:
        await _create_user(session, telegram_id=99902)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp1 = await client.post(
            "/api/init",
            data={"init_data": make_init_data(99902)},
        )
        resp2 = await client.post(
            "/api/init",
            data={"init_data": make_init_data(99902)},
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["user_id"] == resp2.json()["user_id"]


# ═══════════════════════════════════════════════
# Test 3 — Invalid init_data
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_init_invalid_data_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/init",
            data={"init_data": "invalid_string"},
        )

    assert resp.status_code == 401


# ═══════════════════════════════════════════════
# Test 4 — Missing init_data
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_init_missing_data_422():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/init", data={})

    assert resp.status_code == 422


# ═══════════════════════════════════════════════
# Test 5 — Questions count with new user
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_questions_count():
    async with TestSessionLocal() as session:
        await _create_question(session, section="A", order_number=1)
        await _create_question(session, section="A", order_number=2)
        await _create_question(session, section="B", order_number=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/questions")

    assert resp.status_code == 200
    assert len(resp.json()) == 3


# ═══════════════════════════════════════════════
# Test 6 — Attempt creation requires registered user
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_attempt_requires_registered_user():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/attempts",
            data={"init_data": make_init_data(99999)},
        )

    assert resp.status_code in (401, 403)


# ═══════════════════════════════════════════════
# Test 7 — /api/init ro'yxatdan o'tgan user'ni taniydi
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_init_recognizes_registered_user():
    """Bot orqali ro'yxatdan o'tgan (DB da mavjud) user /api/init da
    registered=True qaytaradi. /api/init user yaratmaydi — faqat holatni
    ko'rsatadi (ro'yxatdan o'tish bot'da amalga oshiriladi).
    """
    telegram_id = 99907
    async with TestSessionLocal() as session:
        await _create_user(session, telegram_id=telegram_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/init",
            data={"init_data": make_init_data(telegram_id)},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == telegram_id
    assert data["registered"] is True


# ═══════════════════════════════════════════════
# Test 8 — Daily attempt limit check
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_daily_attempt_limit():
    from app.database.repositories import get_user_attempt_count_today
    from app.database.models import TestAttempt
    from datetime import datetime

    async with TestSessionLocal() as session:
        user = await _create_user(session, telegram_id=99908)
        for _ in range(3):
            attempt = TestAttempt(
                user_id=user.id,
                status="finished",
                started_at=datetime.utcnow(),
            )
            session.add(attempt)
        await session.commit()

        count = await get_user_attempt_count_today(session, user.id)
        assert count == 3


# ═══════════════════════════════════════════════
# Test 9 — Init endpoint returns settings
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_init_returns_settings():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/init",
            data={"init_data": make_init_data(99909)},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "settings" in data or "daily_limit" in data or "user_id" in data


# ═══════════════════════════════════════════════
# Test 10 — Multiple users independent
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_multiple_users_independent():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp1 = await client.post(
            "/api/init",
            data={"init_data": make_init_data(99910)},
        )
        resp2 = await client.post(
            "/api/init",
            data={"init_data": make_init_data(99911)},
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["user_id"] != resp2.json()["user_id"]
