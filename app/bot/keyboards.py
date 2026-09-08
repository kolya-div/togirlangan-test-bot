from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 Taklif havolasi olish",
                    callback_data="invite_link",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="� Test kirish",
                    callback_data="test_access",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="�📝 Savollar boshqaruvi",
                    callback_data="questions",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🚀 Testni boshlash / faollashtirish",
                    callback_data="activate_test",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👥 Foydalanuvchilar va natijalar",
                    callback_data="results",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Bazani tozalash",
                    callback_data="reset_db",
                ),
            ],
        ],
    )


def questions_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📄 Savol kiritish (Docx)",
                    callback_data="upload_docx",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📋 Mavjud savollar",
                    callback_data="list_questions",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Savollarni o'chirish",
                    callback_data="delete_questions",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Orqaga",
                    callback_data="back_to_admin",
                ),
            ],
        ],
    )


def confirm_delete_questions() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Ha, barchasini o'chirish",
                    callback_data="confirm_delete_questions",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data="cancel_delete_questions",
                ),
            ],
        ],
    )


def confirm_reset_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Ha, barchasini o'chirish",
                    callback_data="reset_confirm",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data="reset_cancel",
                ),
            ],
        ],
    )


def activate_test_keyboard(is_active: bool = False) -> InlineKeyboardMarkup:
    text = "🛑 Testni to'xtatish" if is_active else "✅ Testni faollashtirish"
    callback = "deactivate_test" if is_active else "confirm_activate"
    
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=callback,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Orqaga",
                    callback_data="back_to_admin",
                ),
            ],
        ],
    )


def results_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 So'nggi testlar ro'yxati",
                    callback_data="list_results",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔍 O'quvchini qidirish",
                    callback_data="search_user",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔓 Foydalanuvchini blokdan chiqarish",
                    callback_data="unblock_user",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📦 Barcha audiolarni ZIP qilish",
                    callback_data="zip_audios",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🧹 Eski ma'lumotlarni tozalash",
                    callback_data="cleanup",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📍 Hammasi natijalari (docx)",
                    callback_data="export_all_results",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Orqaga",
                    callback_data="back_to_admin",
                ),
            ],
        ],
    )


def cleanup_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Ha, tozalash",
                    callback_data="cleanup_confirm",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data="cleanup_cancel",
                ),
            ],
        ],
    )


def unblock_confirm_keyboard(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Ha, testlarini o'chirish",
                    callback_data=f"unblock_confirm:{tg_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data="unblock_cancel",
                ),
            ],
        ],
    )


def back_button(callback_data: str = "back_to_admin") -> InlineKeyboardMarkup:
    # Agar callback_data "test_access" bo'lsa, maxsus handler chaqirish uchun
    if callback_data == "test_access":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 Orqaga",
                        callback_data="test_access",
                    ),
                ],
            ],
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 Orqaga",
                    callback_data=callback_data,
                ),
            ],
        ],
    )


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📱 Telefon raqamni yuborish",
                    request_contact=True,
                ),
            ],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def webapp_keyboard(webapp_url: str, chat_id: int | None = None) -> InlineKeyboardMarkup:
    # start_param WebApp URL ga PIEVA emas — Telegram uni
    # `initDataUnsafe.start_param` sifatida beradi va faqat chat_id
    # (UX) qiymatini eltadi. Imzolanmagan, shuning uchun faqat UX uchun.
    start_param = str(chat_id) if chat_id is not None else None
    web_app = WebAppInfo(url=webapp_url)
    if start_param:
        # aiogram'da WebAppInfo start_param maydoni mavjud
        web_app = WebAppInfo(url=webapp_url, start_param=start_param)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Testni boshlash",
                    web_app=web_app,
                ),
            ],
        ],
    )


def test_access_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📅 Kunlik (kuniga 1 marta)",
                    callback_data="daily_mode",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⭐ VIP (cheksiz)",
                    callback_data="vip_mode",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Orqaga",
                    callback_data="back_to_admin",
                ),
            ],
        ],
    )