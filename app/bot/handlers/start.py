from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from app.bot.keyboards import admin_menu, webapp_keyboard
from app.bot.states import RegistrationStates
from app.bot.test_state import is_test_active
from app.config import settings
from app.database.database import SessionLocal
from app.database.repositories import (
    get_or_create_user,
    get_test_settings,
    get_user_attempt_count_today,
    get_user_last_attempt,
    get_attempt_answer_count,
)


router = Router()


@router.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext,
) -> None:
    # Telegram /start parametrini olish
    args = message.text.split() if message.text else []
    ref_code = args[1] if len(args) > 1 else None

    # Admin.py ichidagi hozirgi aktiv invite token
    from app.bot.handlers.admin import ACTIVE_INVITE_TOKEN

    async with SessionLocal() as session:
        user = await get_or_create_user(
            session=session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
            admin_ids=settings.admin_id_list,
        )

        # ==========================================
        # ADMIN
        # ==========================================
        if user.is_admin:
            await message.answer(
                "👋 Admin panelga xush kelibsiz.",
                reply_markup=admin_menu(),
            )
            return

        # ==========================================
        # YANGI INVITE LINKNI TEKSHIRISH
        # ==========================================
        if (
            ref_code
            and ACTIVE_INVITE_TOKEN
            and ref_code == ACTIVE_INVITE_TOKEN
            and not user.is_registered
        ):
            await message.answer(
                "🎉 Xush kelibsiz!\n\n"
                "Turk tili speaking testiga taklif qilindingiz.\n"
                "Ro'yxatdan o'tishni boshlaymiz.\n\n"
                "✏️ Ismingiz va familiyangizni kiriting:",
            )

            await state.set_state(
                RegistrationStates.waiting_full_name
            )
            return

        # ==========================================
        # ESKI YOKI NOTO'G'RI LINK
        # ==========================================
        if ref_code and ref_code != ACTIVE_INVITE_TOKEN and not user.is_registered:
            await message.answer(
                "❌ Bu taklif havolasi eskirgan yoki yaroqsiz.\n\n"
                "👤 Admin'dan yangi taklif havolasini oling.",
            )
            return

        # ==========================================
        # LINK YOKI TAKLIFSIZ KIRGAN
        # ==========================================
        if not user.is_registered:
            await message.answer(
                "❌ Siz testga taklif havolasi orqali kirishingiz kerak.\n\n"
                "👤 Admin bilan bog'laning va yangi taklif havolasini oling.",
            )
            return

        # ==========================================
        # TEST FAOL
        # ==========================================
        if is_test_active():
            # Test allaqachon topshirilgan/boshlangan — qayta kirish taqiqlanadi
            last_attempt = await get_user_last_attempt(session, user.id)
            if last_attempt:
                if last_attempt.status == "finished":
                    await message.answer(
                        "❌ Siz allaqachon bu testni topshirgansiz.\n\n"
                        "Testga qayta kirish mumkin emas."
                    )
                    return
                if last_attempt.status in ("active", "started"):
                    answer_count = await get_attempt_answer_count(
                        session, last_attempt.id
                    )
                    if answer_count > 0:
                        await message.answer(
                            "❌ Siz allaqachon testni boshlagansiz.\n\n"
                            "Testga qayta kirish mumkin emas."
                        )
                        return

            # Limit tekshirish
            test_settings = await get_test_settings(session)
            daily_limit = 1  # Default
            current_mode = "daily"  # Default

            if test_settings:
                current_mode = test_settings.test_mode
                if current_mode == "vip":
                    daily_limit = test_settings.vip_limit

            # Bugun qancha test topshirganini hisoblash
            today_attempts = await get_user_attempt_count_today(session, user.id)

            if today_attempts >= daily_limit:
                await message.answer(
                    f"❌ Bugun {daily_limit} marta test topshirish limit tugadi.\n\n"
                    f"Ertaga yana topshirishingiz mumkin.",
                )
                return

            await message.answer(
                "✅ Test faol!\n\n"
                "👇 Quyidagi tugmani bosing va testni boshlang:",
                reply_markup=webapp_keyboard(
                    settings.webapp_url,
                    chat_id=message.chat.id,
                ),
            )
            return

        # ==========================================
        # TEST HALI FAOL EMAS
        # ==========================================
        await message.answer(
            "✅ Ro'yxatdan o'tgansiz.\n"
            "Admin testni faollashtirishini kuting.",
        )