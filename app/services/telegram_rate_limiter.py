"""
Telegram bot-daraja global + per-chat yuborish rate limiter.

Global: 25 msg/s (Telegram ~30 msg/s limitidan xavfsiz).
Per-chat: ~1 msg/s per chat (Telegram ichki flood limit).

Ikkinchi cheklov muhim: hisobot 4-5 xabar yuboradi (header + audio +
text + summary). 50 user bir vaqtda tugasa, har biriga 5 msg
ketma-ket → bir chat'da 5 msg 5 soniyada → Telegram 429 berishi mumkin.

Muhim arxitektura tanlovi: ikkita event loop (Loop A = bot, Loop B = FastAPI)
mavjud. Shuning uchun `asyncio.Lock`/`Semaphore` ISHLATA OLMAYMIZ — ular
loop'ga bog'lanib, boshqa loopdan ishlatilsa "bound to a different event loop"
xatosi beradi. O'rniga `threading.Lock` + `time.monotonic()` ishlatamiz —
loop-agnostik va thread-safe. Kutish esa `asyncio.sleep` orqali qo'ng'iroq
chiruvchining o'z loopida bajariladi.
"""

import asyncio
import logging
import threading
import time

logger = logging.getLogger(__name__)

# ────────────── GLOBAL RATE LIMIT ──────────────
TELEGRAM_RATE_PER_SECOND = 25.0
_MIN_INTERVAL = 1.0 / TELEGRAM_RATE_PER_SECOND

_lock = threading.Lock()
_next_allowed_at = 0.0  # time.monotonic() asosida

# ────────────── PER-CHAT RATE LIMIT ──────────────
# Telegram flood control: ~1 msg/s per chat, ~20 msg/min per group.
# Hisobot xabarlari sequential — lekin 50+ user bir vaqtda tugasa,
# interleaving yuz beradi. Per-chat gate 1.5s interval (xavfsiz zahira).
PER_CHAT_INTERVAL = 1.5  # soniya (har bir chat uchun minimal interval)
_chat_last_allowed: dict[int, float] = {}  # chat_id → time.monotonic()
_chat_lock = threading.Lock()
_chat_cleanup_counter = 0  # Har 1000 chaqiruvda tozalash


async def wait_send_gate() -> None:
    """Global + per-chat tezlikni ta'minlash uchun kutadi."""
    global _next_allowed_at, _chat_cleanup_counter

    # 1. Global gate
    wait = 0.0
    with _lock:
        now = time.monotonic()
        if now < _next_allowed_at:
            wait = _next_allowed_at - now
            _next_allowed_at += _MIN_INTERVAL
        else:
            _next_allowed_at = now + _MIN_INTERVAL
    if wait > 0:
        await asyncio.sleep(wait)


async def wait_chat_gate(chat_id: int) -> None:
    """Per-chat tezlikni ta'minlash uchun kutadi."""
    global _chat_cleanup_counter

    with _chat_lock:
        now = time.monotonic()
        last = _chat_last_allowed.get(chat_id, 0.0)
        wait = 0.0
        if now - last < PER_CHAT_INTERVAL:
            wait = PER_CHAT_INTERVAL - (now - last)
        _chat_last_allowed[chat_id] = now + wait

        # Periodic cleanup: eski entrylarni tozalash
        _chat_cleanup_counter += 1
        if _chat_cleanup_counter >= 1000:
            _chat_cleanup_counter = 0
            expired = [
                cid for cid, t in _chat_last_allowed.items()
                if now - t > 300  # 5 daqiqa oldingi
            ]
            for cid in expired:
                del _chat_last_allowed[cid]

    if wait > 0:
        await asyncio.sleep(wait)


_installed = False


def install_bot_throttle() -> None:
    """`aiogram.Bot.__call__` ni global gate bilan o'rab oladi.

    Har qanday Telegram API method (send_message, send_audio,
    answer_callback_query, edit_message_text, ...) `Bot.__call__` orqali
    o'tadi (aiogram 3). Bir nuqtada o'rab qo'ysak, barcha yuborishlar —
    hisobotlar ham, handler'lar ham — bitta global chegaraga bo'ysunadi.

    Idempotent: bir necha marta chaqirilsa ham faqat bir marta o'raydi.
    """
    global _installed
    if _installed:
        return

    import aiogram

    _orig_call = aiogram.Bot.__call__

    async def _throttled_call(self, method, request_timeout=None):
        await wait_send_gate()
        return await _orig_call(self, method, request_timeout=request_timeout)

    aiogram.Bot.__call__ = _throttled_call
    _installed = True
    logger.info(
        "Telegram global yuborish limiter o'rnatildi: %s msg/s",
        TELEGRAM_RATE_PER_SECOND,
    )
