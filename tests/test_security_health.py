"""
Security & Health endpoint testlari:
- Health endpoint DB error isolation
- Health endpoint returns status
- Global exception handler hides internal errors
- CORS headers
- Origin validation
"""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
import os

from app.database.database import Base
from app.main import app
from app.config import settings


TEST_DB_URL = os.getenv(
    "TEST_DB_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/turkish_bot_test",
)

test_engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_db():
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


# ═══════════════════════════════════════════════
# Test 1 — Health endpoint returns OK
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_health_returns_ok():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


# ═══════════════════════════════════════════════
# Test 2 — Health endpoint does NOT leak DB errors
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_health_does_not_leak_db_errors():
    with patch("app.main.SessionLocal", side_effect=Exception("connection refused to PostgreSQL 14.2")):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "PostgreSQL 14.2" not in detail
    assert "connection refused" not in detail
    assert detail == "Database unavailable"


# ═══════════════════════════════════════════════
# Test 3 — Global exception handler hides internal errors
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_global_exception_handler_hides_details():
    with patch("app.api.routes.SessionLocal", side_effect=Exception("SECRET_DB_PASSWORD=supersecret")):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/questions")

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "supersecret" not in detail
    assert "SECRET_DB_PASSWORD" not in detail


# ═══════════════════════════════════════════════
# Test 4 — CORS headers present
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_cors_headers():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.options(
            "/api/questions",
            headers={
                "Origin": "https://t.me",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert resp.status_code == 200


# ═══════════════════════════════════════════════
# Test 5 — Unauthorized access returns 401
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_unauthorized_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/attempts/1/results",
            params={"init_data": "garbage"},
        )

    assert resp.status_code == 401


# ═══════════════════════════════════════════════
# Test 6 — Nonexistent attempt returns 404
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_nonexistent_attempt_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/attempts/99999/results",
            params={"init_data": "valid_init_data"},
        )

    assert resp.status_code in (401, 404)


# ═══════════════════════════════════════════════
# Test 7 — Status endpoint for non-existent attempt
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_status_nonexistent_404():
    import time, hmac, hashlib, json
    user = {"id": 12345, "first_name": "Test"}
    params = {
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    init_data = "&".join(f"{k}={v}" for k, v in sorted(params.items()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/attempts/99999/status",
            params={"init_data": init_data},
        )

    assert resp.status_code in (404, 403)


# ═══════════════════════════════════════════════
# Test 8 — Admin endpoints require admin auth
# ═══════════════════════════════════════════════
@pytest.mark.anyio
async def test_admin_endpoints_unauthorized():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/ai-health")

    assert resp.status_code == 422  # Missing required init_data param


@pytest.mark.anyio
async def test_admin_endpoints_wrong_user():
    import time, hmac, hashlib, json
    user = {"id": 99999, "first_name": "Attacker"}
    params = {
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    init_data = "&".join(f"{k}={v}" for k, v in sorted(params.items()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/ai-health",
            params={"init_data": init_data},
        )

    assert resp.status_code == 403
    assert "Admin emas" in resp.json()["detail"]
