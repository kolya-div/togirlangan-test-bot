"""
Questions endpoint testlari:
- Question list olish
- Empty question list
- Question fields validation
- Cache headers
- Unauthorized access (questions public — auth kerak emas)
"""

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from unittest.mock import patch
import os

from app.database.database import Base
from app.database.models import Question
from app.main import app


TEST_DB_URL = os.getenv(
    "TEST_DB_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/turkish_bot_test",
)

test_engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


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
# Test 1 — Question list olish
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_questions_returns_list():
    async with TestSessionLocal() as session:
        await _create_question(session, section="A", order_number=1)
        await _create_question(session, section="B", order_number=2)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/questions")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2


# ═══════════════════════════════════════════════
# Test 2 — Empty question list
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_questions_empty():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/questions")

    assert resp.status_code == 200
    assert resp.json() == []


# ═══════════════════════════════════════════════
# Test 3 — Question fields validation
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_questions_have_required_fields():
    async with TestSessionLocal() as session:
        await _create_question(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/questions")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1

    q = data[0]
    required_fields = ["id", "section", "order_number", "text", "preparation_seconds", "answer_seconds"]
    for field in required_fields:
        assert field in q, f"Missing field: {field}"


# ═══════════════════════════════════════════════
# Test 4 — Cache headers (no-cache)
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_questions_no_cache_headers():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/questions")

    assert resp.status_code == 200
    assert "no-store" in resp.headers.get("cache-control", "")


# ═══════════════════════════════════════════════
# Test 5 — Questions are ordered by section + order_number
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_questions_ordered():
    async with TestSessionLocal() as session:
        await _create_question(session, section="B", order_number=2)
        await _create_question(session, section="A", order_number=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/questions")

    data = resp.json()
    assert data[0]["section"] == "A"
    assert data[0]["order_number"] == 1
    assert data[1]["section"] == "B"
    assert data[1]["order_number"] == 2


# ═══════════════════════════════════════════════
# Test 6 — Inactive questions NOT returned
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_inactive_questions_filtered():
    async with TestSessionLocal() as session:
        await _create_question(session, is_active=True)
        await _create_question(session, is_active=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/questions")

    data = resp.json()
    assert len(data) == 1
    assert data[0]["is_active"] is True


# ═══════════════════════════════════════════════
# Test 7 — Questions endpoint is public (no auth needed)
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_questions_public_no_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/questions")

    assert resp.status_code == 200
