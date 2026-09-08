"""
Telegram bot-daraja global yuborish rate limiter (token bucket / min-interval).

Nega: Telegram botlar uchun UMUMIY (barcha chatlar bo'yicha) tezlik chegarasi
mavjud (~30 xabar/sekund). BIR XIL bot tokenidan yuboriladigan HAMMA xabarlar
— hisobot xabarlari ham, bot handler'laridagi oddiy suhbat xabarlari ham
(message.answer, callback.message.answer va h.k.) — o'sha chegaraga tortiladi.
70-100 foydalanuvchi bir vaqtda testni boshlaganda va/ yoki tugatganda barcha
yuborishlar birlashib, ular sonini kesib o'tishi mumkin.

Ilgari faqat hisobot yo'li (`_send_with_retry`) 429'ga REAKTIV javob berardi.
Bu modul PROAKTIV global gate beradi: har qanday `aiogram.Bot` `__call__`
chaqiruvidan (har qanday API method, har qanday Bot instansiyasi, har qanday
event loop da) o'tadi.

Muhim arxitektura tanlovi: ikkita event loop (Loop A = bot, Loop B = FastAPI)
mavjud. Shuning uchun `asyncio.Lock`/`Semaphore` ISHLATA OLMAYMIZ — ular
loop'ga bog'lanib, boshqa loopdan ishlatilsa "bound to a different event loop"
xatosi beradi. O'rniga `threading.Lock` + `time.monotonic()` ishlatamiz —
loop-agnostik va thread-safe. Kutish esa `asyncio.sleep` orqali qo'ng'iroq
qiluvchining o'z loopida bajariladi.
"""

import asyncio
import logging
import threading
import time

logger = logging.getLogger(__name__)

# Telegram botlar uchun umumiy chegarasi ~30 msg/sekund. Xavfsizlik zahirasi
# bilan 25 msg/sekund qilib qo'yamiz — 429 juda kam chiqadi, lekin yetkazish
# hali ham tez.
TELEGRAM_RATE_PER_SECOND = 25.0

# Umumiy interval: 1 / tezlik
_MIN_INTERVAL = 1.0 / TELEGRAM_RATE_PER_SECOND

_lock = threading.Lock()
_next_allowed_at = 0.0  # time.monotonic() asosida


async def wait_send_gate() -> None:
    """Umumiy tezlikni ta'minlash uchun kerak bo'lsa qisqa kutadi.

    Tezlik cheklovi 25 msg/s -> orasida ~0.04 s. Bu interval ichida ko'p
    coroutine kelsa, barchasi tartibli o'tadi (token bucket, burst'ni ham
    osonlashtiradi).
    """
    global _next_allowed_at
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
