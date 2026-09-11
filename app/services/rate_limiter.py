"""
API rate limit boshqaruvi.
Gemini bepul: ~15 RPM per key → bir nechta kalit bo'lsa sum ishlatiladi.
Smart queue: navbat bilan ishlaydi, 429 xato bermaydi.
"""

import asyncio
import time
import logging

logger = logging.getLogger(__name__)

# Gemini: RPM config.py dan olinadi (free=15, paid=300+).
# Free: ~15 RPM per key = har 4 soniyada 1 ta request per key.
# Paid (Tier 1+): 300 RPM per key — AI Studio'dan aniqlang.
# Bir nechta kalit bo'lsa, umumiy RPM = GEMINI_RPM_PER_KEY × kalit_soni.
GROQ_MIN_INTERVAL = 2.0    # soniya (30 RPM = 60/30 = 2s)

_last_gemini_call = 0.0
_last_groq_call = 0.0
_gemini_lock = asyncio.Lock()
_groq_lock = asyncio.Lock()


def _gemini_interval() -> float:
    """Gemini uchun interval — RPM konfiguratsiyasiga qarab dinamik."""
    from app.config import settings
    key_count = max(1, len(settings.gemini_keys_list))
    rpm_per_key = max(1, getattr(settings, "gemini_rpm_per_key", 15))
    total_rpm = rpm_per_key * key_count
    return 60.0 / total_rpm


async def wait_gemini():
    """Gemini uchun kutish — kalitlar soniga qarab dinamik interval."""
    global _last_gemini_call
    async with _gemini_lock:
        interval = _gemini_interval()
        now = time.monotonic()
        elapsed = now - _last_gemini_call
        if elapsed < interval:
            wait_time = interval - elapsed
            logger.debug(f"Gemini rate limit: {wait_time:.1f}s kutilmoqda")
            await asyncio.sleep(wait_time)
        _last_gemini_call = time.monotonic()


async def wait_groq():
    """Groq uchun kutish — har 2 soniyada 1 ta request."""
    global _last_groq_call
    async with _groq_lock:
        now = time.monotonic()
        elapsed = now - _last_groq_call
        if elapsed < GROQ_MIN_INTERVAL:
            wait_time = GROQ_MIN_INTERVAL - elapsed
            logger.debug(f"Groq rate limit: {wait_time:.1f}s kutilmoqda")
            await asyncio.sleep(wait_time)
        _last_groq_call = time.monotonic()
