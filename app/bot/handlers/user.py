from aiogram import Router
from aiogram.types import Message

from app.config import settings
from app.database.repositories import get_or_create_user
from sqlalchemy.ext.asyncio import AsyncSession


router = Router()


async def user_start_handler(
    message: Message,
    session: AsyncSession,
) -> None:
    user = await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        admin_ids=settings.admin_id_list,
    )

    if user.is_admin:
        return

    if not user.is_registered:
        await message.answer(
            "Siz testga taklif havolasi orqali kirishingiz kerak.\n"
            "Admin sizga link yuboradi.",
        )
        return

    await message.answer(
        "✅ Ro‘yxatdan o‘tgansiz.\nAdmin testni faollashtirishini kuting.",
    )