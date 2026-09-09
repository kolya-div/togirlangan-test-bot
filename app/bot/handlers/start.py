from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from app.bot.keyboards import admin_menu, webapp_keyboard
from app.bot.states import RegistrationStates
# FIX #10: Modul import qilinadi (value emas) — token o'zgarganda ham yangi qiymat ko'rinadi.
# Avval: `from app.bot.handlers.admin import ACTIVE_INVITE_TOKEN`
# Bu Python'da qiymat NUSXALANADI, ya'ni admin token o'zgartirsa start.py eski None ni ko'rardi.
from app.bot import test_state  # is_test_active(), get_invite_token()
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
    args = message.text.split() if message.text else []
    ref_code = args[1] if len(args) > 1 else None

    # FIX #10: Modul orqali o'qiladi — har doim joriy qiymat.
    active_token = test_state.get_invite_token()

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
            and active_token
            and ref_code == active_token
            and not user.is_registered
        ):
            await message.answer(
                "🎉 Xush kelibsiz!\n\n"
                "Turk tili speaking testiga taklif qilindingiz.\n"
                "Ro'yxatdan o'tishni boshlaymiz.\n\n"
                "✏️ Ismingiz va familiyangizni kiriting:",
            )
            await state.set_state(RegistrationStates.waiting_full_name)
            return

        # ==========================================
        # ESKI YOKI NOTO'G'RI LINK
        # ==========================================
        if ref_code and ref_code != active_token and not user.is_registered:
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
        if test_state.is_test_active():
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

            test_settings = await get_test_settings(session)
            daily_limit = 1
            current_mode = "daily"

            if test_settings:
                current_mode = test_settings.test_mode
                if current_mode == "vip":
                    daily_limit = test_settings.vip_limit

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