import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import ExceptionMessageFilter, ExceptionTypeFilter
from aiogram.types import ErrorEvent

from .start import router as start_router
from .admin import router as admin_router
from .registration import router as registration_router
from .user import router as user_router
from .voice import router as voice_router

logger = logging.getLogger(__name__)

# Bitta umumiy router
handlers_router = Router()
handlers_router.include_router(start_router)
handlers_router.include_router(admin_router)
handlers_router.include_router(registration_router)
handlers_router.include_router(user_router)
handlers_router.include_router(voice_router)


# Telegram tugma bosilishiga (callback) ~15 soniyada javob kutadi. Bot
# o'chiq/qayta ishga tushayotganda bosilgan tugma keyin qayta ishlanadi —
# amal bajariladi, lekin oxiridagi callback.answer() shu xatoni beradi.
# Zararsiz: logni traceback bilan to'ldirmaslik uchun ushlaymiz.
@handlers_router.errors(
    ExceptionTypeFilter(TelegramBadRequest),
    # re.match — matn boshidan tekshiriladi ("Telegram server says - ...")
    ExceptionMessageFilter(r".*(query is too old|query ID is invalid)"),
)
async def stale_callback_error(event: ErrorEvent) -> bool:
    logger.warning(
        "Eskirgan tugma bosilishi (javob muddati o'tgan) — e'tiborsiz qoldirildi: %s",
        event.exception,
    )
    return True


__all__ = ["handlers_router"]
