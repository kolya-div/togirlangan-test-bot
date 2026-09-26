"""
Bot handler tuzatishlari:
- Ro'yxatdan o'tishda kiritilgan ism saqlanadi (oldin Telegram profil ismi qolardi)
- /register taklif havolasisiz ro'yxatdan o'tkazmaydi
- Matn o'rniga stiker/rasm yuborilsa ism bosqichi yiqilmaydi
- Admin natijalar sahifasi klaviaturasi yaratiladi (oldin TypeError)
- Natijalar qatorida ism HTML escape qilinadi
- /cancel holatni tozalaydi
"""

import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.bot.handlers import admin, registration
from app.bot.states import RegistrationStates
from app.database.database import Base
from app.database.models import User

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
    with patch.object(registration, "SessionLocal", TestSessionLocal):
        yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def _message(user_id=111, text=None, contact=None, full_name="Profil Ism"):
    msg = MagicMock()
    msg.text = text
    msg.contact = contact
    msg.from_user = SimpleNamespace(id=user_id, username="u", full_name=full_name)
    msg.answer = AsyncMock()
    return msg


def _state(data=None):
    state = MagicMock()
    state.get_data = AsyncMock(return_value=data or {})
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


@pytest.mark.anyio
async def test_typed_full_name_is_saved_on_registration():
    async with TestSessionLocal() as s:
        # /start da Telegram profil ismi bilan yaratilgan user
        s.add(User(telegram_id=111, full_name="Profil Ism"))
        await s.commit()

    msg = _message(contact=SimpleNamespace(user_id=111, phone_number="+998901112233"))
    await registration.process_phone(msg, _state({"full_name": "Ali Valiyev"}))

    async with TestSessionLocal() as s:
        user = (await s.execute(select(User).where(User.telegram_id == 111))).scalar_one()
    assert user.full_name == "Ali Valiyev"
    assert user.phone == "+998901112233"
    assert user.is_registered is True


@pytest.mark.anyio
async def test_register_command_requires_invite_link():
    msg = _message()
    state = _state()
    await registration.start_registration(msg, state)

    state.set_state.assert_not_awaited()
    assert "taklif havolasi" in msg.answer.await_args.args[0]


@pytest.mark.anyio
async def test_full_name_step_survives_non_text_message():
    msg = _message(text=None)  # stiker/rasm
    state = _state()
    await registration.process_full_name(msg, state)

    state.set_state.assert_not_awaited()
    assert "qisqa" in msg.answer.await_args.args[0]


@pytest.mark.anyio
async def test_results_page_keyboard_builds():
    kb = admin._results_page_keyboard(offset=10, total=35)
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert texts == ["⬅️ Oldingi", "Keyingi ➡️", "🔙 Orqaga"]


@pytest.mark.anyio
async def test_attempt_line_escapes_html():
    attempt = SimpleNamespace(
        id=1, status="finished", score=50, level="B1",
        started_at=datetime(2026, 9, 26, 19, 0),  # UTC → 00:00 Toshkent
    )
    user = SimpleNamespace(full_name="<b>Ali</b> & Co", username="a<x>", telegram_id=5)
    line = admin._attempt_line(attempt, user)
    assert "&lt;b&gt;Ali&lt;/b&gt; &amp; Co" in line
    assert "a&lt;x&gt;" in line
    assert "2026-09-27 00:00" in line


@pytest.mark.anyio
async def test_cancel_clears_state():
    msg = _message(user_id=999999999, text="/cancel")
    state = _state()
    await admin.cancel_handler(msg, state)
    state.clear.assert_awaited_once()
    msg.answer.assert_awaited_once()
