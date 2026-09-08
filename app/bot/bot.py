from aiogram import Bot, Dispatcher

from app.config import settings
from app.services.telegram_rate_limiter import install_bot_throttle

# Butun bot uchun global Telegram yuborish rate limiter'ini o'rnatish.
# Buni birinchi importda bajarish kerak — BARCHA `aiogram.Bot` instansiyalari
# (umumiy bot va hisobot/yangi `Bot`lar) bir xil chegaraga bo'ysunadi.
install_bot_throttle()

bot = Bot(token=settings.bot_token)
dp = Dispatcher()