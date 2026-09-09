"""
Test holati va invite token boshqaruvi.

BUG FIX #1: Avval _test_active_global = False (in-memory) edi —
bot restart bo'lsa holat yo'qolardi. Endi DB da saqlanadi.

BUG FIX #2: ACTIVE_INVITE_TOKEN ham in-memory edi.
Endi DB da saqlanadi — restart safe.

Tezlik uchun in-memory cache ham saqlanadi, lekin DB —
yagona haqiqat manbai (source of truth).
"""

import logging

logger = logging.getLogger(__name__)

# In-memory cache — DB ga har safar murojaat qilmaslik uchun.
# Bot ishga tushganda DB dan yuklanadi (agar kerak bo'lsa).
_test_active_cache: bool = False
_invite_token_cache: str | None = None


# ─────────────────────────── TEST ACTIVE ───────────────────────────

def set_test_active_cache(active: bool) -> None:
    """Faqat cache ni yangilaydi. DB ga yozish uchun async funksiyadan foydalaning."""
    global _test_active_cache
    _test_active_cache = active


def is_test_active() -> bool:
    """Sinxron — handler lardan chaqirish uchun (cache dan o'qiydi)."""
    return _test_active_cache


async def set_test_active(active: bool) -> None:
    """DB ga yozadi va cache ni yangilaydi."""
    from app.database.database import SessionLocal
    from app.database.repositories import get_test_settings, _upsert_test_active

    global _test_active_cache
    _test_active_cache = active

    async with SessionLocal() as session:
        await _upsert_test_active(session, active)

    logger.info("Test holati o'zgartirildi: %s", "FAOL" if active else "O'CHIQ")


async def load_test_state_from_db() -> None:
    """Bot ishga tushganda DB dan holat va tokenni yuklaydi.
    app/main.py da bot start da bir marta chaqiriladi.
    """
    from app.database.database import SessionLocal
    from app.database.repositories import get_test_settings

    global _test_active_cache, _invite_token_cache

    async with SessionLocal() as session:
        settings_row = await get_test_settings(session)
        if settings_row:
            _test_active_cache = settings_row.is_active
            _invite_token_cache = settings_row.invite_token
            logger.info(
                "DB dan yuklandi: test_active=%s, invite_token=%s",
                _test_active_cache,
                "bor" if _invite_token_cache else "yo'q",
            )
        else:
            logger.info("DB da test_settings yo'q, default holat ishlatiladi.")


# ─────────────────────────── INVITE TOKEN ───────────────────────────

def get_invite_token() -> str | None:
    """Sinxron — handler lardan chaqirish uchun (cache dan o'qiydi)."""
    return _invite_token_cache


async def set_invite_token(token: str | None) -> None:
    """DB ga yozadi va cache ni yangilaydi."""
    from app.database.database import SessionLocal
    from app.database.repositories import _upsert_invite_token

    global _invite_token_cache
    _invite_token_cache = token

    async with SessionLocal() as session:
        await _upsert_invite_token(session, token)

    logger.info("Invite token yangilandi.")