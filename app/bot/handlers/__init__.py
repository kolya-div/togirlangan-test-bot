from aiogram import Router
from .start import router as start_router
from .admin import router as admin_router
from .registration import router as registration_router
from .user import router as user_router
from .voice import router as voice_router

# Bitta umumiy router
handlers_router = Router()
handlers_router.include_router(start_router)
handlers_router.include_router(admin_router)
handlers_router.include_router(registration_router)
handlers_router.include_router(user_router)
handlers_router.include_router(voice_router)

__all__ = ["handlers_router"]