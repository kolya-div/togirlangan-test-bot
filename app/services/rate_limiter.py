"""
API rate limit boshqaruvi.
Gemini bepul: ~15 RPM → 4 soniyada 1 ta request.
Smart queue: navbat bilan ishlaydi, 429 xato bermaydi.
"""

import asyncio
import time
import logging

logger = logging.getLogger(__name__)

# Gemini bepul: ~15 RPM = har 4 soniyada 1 ta request
# 3 ta worker = bir vaqtda 3 ta, lekin 4 soniyada bir guruhi to'liq
GEMINI_MIN_INTERVAL = 4.0  # soniya (15 RPM = 60/15 = 4s)
GROQ_MIN_INTERVAL = 2.0    # soniya (30 RPM = 60/30 = 2s)

_last_gemini_call = 0.0
_last_groq_call = 0.0
_gemini_lock = asyncio.Lock()
_groq_lock = asyncio.Lock()


async def wait_gemini():
    """Gemini uchun kutish — har 4 soniyada 1 ta request."""
    global _last_gemini_call
    async with _gemini_lock:
        now = time.monotonic()
        elapsed = now - _last_gemini_call
        if elapsed < GEMINI_MIN_INTERVAL:
            wait_time = GEMINI_MIN_INTERVAL - elapsed
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
