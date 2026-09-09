import asyncio
import json
import os
import zipfile
import logging
import secrets
from pathlib import Path

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# FIX #1 & #2: test_state moduli orqali DB da saqlanadigan holatdan foydalanamiz.
# Avval: from app.bot.test_state import set_test_active, is_test_active
# Va:    ACTIVE_INVITE_TOKEN = None  (global volatile variable)
from app.bot import test_state  # is_test_active(), set_test_active(), get/set_invite_token()

from app.bot.keyboards import (
    admin_menu,
    confirm_reset_keyboard,
    questions_menu,
    confirm_delete_questions,
    activate_test_keyboard,
    results_menu,
    cleanup_confirm_keyboard,
    unblock_confirm_keyboard,
    back_button,
    webapp_keyboard,
    test_access_menu,
)
from app.bot.states import (
    AdminQuestionsStates,
    AdminActivateStates,
    AdminResultsStates,
    AdminTestAccessStates,
)
from app.config import settings
from app.database.models import User
from app.database.repositories import (
    delete_all_data,
    get_all_questions,
    add_question,
    delete_all_questions,
    get_questions_count,
    get_registered_users,
    get_test_settings,
    create_or_update_test_settings,
    get_user_attempt_count_today,
    get_recent_attempts,
    get_attempts_count,
    search_users,
    get_user_attempts,
)
from app.services.cleanup_service import run_cleanup, delete_user_attempts
from app.services.daily_export_wipe import (
    ExportBusyError,
    is_in_progress,
    run_admin_export_only,
)

logger = logging.getLogger(__name__)

from app.services.docx_parser import parse_docx_questions
from app.services.ai_docx_service import parse_docx_with_ai

router = Router()

# Broadcast xabarlari orasidagi minimal interval (Telegram flood limit xavfsizligi).
_BROADCAST_INTERVAL = 0.05  # 20 msg/s — Telegram 30 msg/s limitidan past


async def _safe_edit(message, **kwargs):
    """edit_text yoki edit_media xatosini tutadi (message not modified)."""
    try:
        return await message.edit_text(**kwargs)
    except Exception:
        return None


async def _download_docx(message: Message) -> Path | None:
    """Yuborilgan docx faylni data/uploads ga yuklab, yo'lini qaytaradi."""
    if not message.document:
        await message.answer("❌ Iltimos, docx fayl yuboring.")
        return None

    if not message.document.file_name.endswith('.docx'):
        await message.answer("❌ Faqat .docx formatdagi fayllar qabul qilinadi.")
        return None

    docx_dir = Path(__file__).resolve().parent.parent.parent / "data" / "uploads"
    docx_dir.mkdir(parents=True, exist_ok=True)
    file_path = docx_dir / message.document.file_name

    await message.bot.download(message.document, destination=file_path)
    return file_path


async def _save_questions(session: AsyncSession, questions: list[dict]) -> int:
    """Parse qilingan savollarni bazaga yozadi, saqlanganlar sonini qaytaradi."""
    count = 0
    for q in questions:
        await add_question(
            session=session,
            section=q["section"],
            order_number=q["order_num"],
            text=q["text"],
            preparation_seconds=q["prep_time"],
            answer_seconds=q["answer_time"],
            sub_questions=q.get("sub_questions"),
            image_path=q.get("image_path"),
            pro_points=q.get("pro_points"),
            con_points=q.get("con_points"),
            max_points=q.get("points"),
        )
        count += 1
    return count


# ==================== ASOSIY ADMIN CALLBACK ====================

@router.callback_query(F.data == "test_access")
async def test_access_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """
    FIX #3: Duplicate `test_access` handler o'chirildi.
    Avval ikkinchi `test_access_back_handler` ham bor edi — aiogram
    birinchisini ishlatardi, ikkinchisi hech qachon ishlamasdi.
    Ikkalasi bitta handlerga birlashtirildi.
    """
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await state.set_state(AdminTestAccessStates.menu)

    from app.database.database import SessionLocal
    async with SessionLocal() as session:
        test_settings = await get_test_settings(session)

    current_mode = "Kunlik" if test_settings and test_settings.test_mode == "daily" else "VIP"
    current_limit = test_settings.vip_limit if test_settings else 1

    await _safe_edit(
        callback.message,
        text=f"🚪 Test kirish sozlamalari\n\n"
        f"Hozirgi rejim: {current_mode}\n"
        f"VIP limit: {current_limit} ta/kun\n\n"
        f"Rejimni tanlang:",
        reply_markup=test_access_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "daily_mode")
async def daily_mode_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    from app.database.database import SessionLocal
    async with SessionLocal() as session:
        await create_or_update_test_settings(session, "daily", 1)

    await _safe_edit(
        callback.message,
        text="✅ Kunlik rejim faollashtirildi!\n\n"
        "Foydalanuvchilar kuniga 1 marta test topshira oladi.\n"
        "Ertaga 00:00 da limit avtomatik tiklanadi.",
        reply_markup=test_access_menu(),
    )
    await callback.answer("Kunlik rejim faollashtirildi!")


@router.callback_query(F.data == "vip_mode")
async def vip_mode_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await state.set_state(AdminTestAccessStates.waiting_vip_limit)
    await _safe_edit(
        callback.message,
        text="⭐ VIP rejim\n\n"
        "Foydalanuvchilar kuniga necha marta test topshira olishini kiriting:\n"
        "Masalan: 5\n\n"
        "🔙 Bekor qilish uchun /cancel",
        reply_markup=back_button("test_access"),
    )
    await callback.answer()


@router.message(AdminTestAccessStates.waiting_vip_limit)
async def process_vip_limit(message: Message, state: FSMContext) -> None:
    try:
        vip_limit = int(message.text.strip())
        if vip_limit < 1:
            await message.answer("❌ Limit kamida 1 bo'lishi kerak.")
            return
    except ValueError:
        await message.answer("❌ Iltimos, faqat raqam yuboring.")
        return

    from app.database.database import SessionLocal
    async with SessionLocal() as session:
        await create_or_update_test_settings(session, "vip", vip_limit)

    await message.answer(
        f"✅ VIP rejim faollashtirildi!\n\n"
        f"Foydalanuvchilar kuniga {vip_limit} marta test topshira oladi.\n"
        f"Ertaga 00:00 da limit avtomatik tiklanadi.",
        reply_markup=test_access_menu(),
    )
    await state.set_state(AdminTestAccessStates.menu)


@router.callback_query(F.data == "invite_link")
async def invite_link_handler(callback: CallbackQuery) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    bot_info = await callback.bot.get_me()

    # FIX #2: Token DB ga saqlanadi — bot restart bo'lsa ham ishlaydi.
    new_token = secrets.token_urlsafe(16)
    await test_state.set_invite_token(new_token)

    invite_link = (
        f"https://t.me/{bot_info.username}"
        f"?start={new_token}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤖 Botga kirish",
                    url=invite_link,
                )
            ]
        ]
    )

    await callback.message.answer(
        "🔗 Yangi taklif havolasi:\n\n"
        f"<code>{invite_link}</code>\n\n"
        "📋 Qo'llanma:\n"
        "1. Havolani foydalanuvchiga yuboring\n"
        "2. Foydalanuvchi havolani ochadi\n"
        "3. Bot ochilgach «Start» tugmasini bosadi\n\n"
        "⚠️ Yangi link yaratilganda eski link bekor qilinadi.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    await callback.answer("✅ Yangi link yaratildi")


@router.callback_query(F.data == "questions")
async def questions_menu_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await state.set_state(AdminQuestionsStates.menu)
    await _safe_edit(
        callback.message,
        text="📝 Savollar boshqaruvi\n\n"
        "Quyidagi amallardan birini tanlang:",
        reply_markup=questions_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "activate_test")
async def activate_test_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await state.set_state(AdminActivateStates.confirm)

    status = "✅ FAOL" if test_state.is_test_active() else "🛑 O'CHIQ"
    await _safe_edit(
        callback.message,
        text=f"🚀 Test holati: {status}\n\n"
        f"Testni faollashtirish yoki to'xtatishni xohlaysizmi?",
        reply_markup=activate_test_keyboard(is_active=test_state.is_test_active()),
    )
    await callback.answer()


@router.callback_query(F.data == "results")
async def results_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await state.set_state(AdminResultsStates.menu)
    await _safe_edit(
        callback.message,
        text="👥 Foydalanuvchilar va natijalar\n\n"
        "Quyidagi amallardan birini tanlang:",
        reply_markup=results_menu(),
    )
    await callback.answer()


# ==================== SAVOLLAR MENYUSI ====================

@router.callback_query(F.data == "upload_docx")
async def upload_docx_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await state.set_state(AdminQuestionsStates.waiting_docx)
    await _safe_edit(
        callback.message,
        text="📄 Docx faylni yuboring (oddiy parser).\n\n"
        "Fayl quyidagi formatda bo'lishi kerak:\n"
        "• Bölüm 1.1, Bölüm 1.2, Bölüm 2, Bölüm 3\n"
        "• Har bir savolda: Tayyorlanish: XX, Javob: XX\n\n"
        "🔙 Bekor qilish uchun /cancel ni bosing.",
        reply_markup=back_button("questions"),
    )
    await callback.answer()


@router.callback_query(F.data == "upload_docx_ai")
async def upload_docx_ai_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    if not getattr(settings, "openai_api_key", None):
        await callback.answer(
            "OPENAI_API_KEY sozlanmagan — oddiy parser dan foydalaning",
            show_alert=True,
        )
        return

    await state.set_state(AdminQuestionsStates.waiting_docx_ai)
    await _safe_edit(
        callback.message,
        text="🤖 Docx faylni yuboring (AI tahlil qiladi).\n\n"
        "AI hujjatni o'zi o'qib, savollarni bo'limlarga ajratib, "
        "rasmlarni o'z savollariga moslaydi. Format har xil bo'lsa ham ishlaydi.\n\n"
        "⏳ Tahlil 10-30 soniya vaqt olishi mumkin.\n"
        "🔙 Bekor qilish uchun /cancel ni bosing.",
        reply_markup=back_button("questions"),
    )
    await callback.answer()


@router.message(AdminQuestionsStates.waiting_docx)
async def process_docx(message: Message, state: FSMContext, session: AsyncSession) -> None:
    file_path = await _download_docx(message)
    if not file_path:
        return

    try:
        questions = await parse_docx_questions(file_path)
    except Exception as e:
        await message.answer(f"❌ Faylni o'qishda xato: {e}")
        return

    if not questions:
        await message.answer("❌ Faylda savollar topilmadi. Formatni tekshiring.")
        return

    count = await _save_questions(session, questions)

    await message.answer(
        f"✅ {count} ta savol muvaffaqiyatli yuklandi!\n\n" +
        "\n".join([
            f"• Bölüm {q['section']}-{q['order_num']}: "
            + (f"[🖼 x{(q.get('image_path') or '').count('|') + 1}] " if q.get('image_path') else "")
            + (q['text'][:50] or "(rasm savoli)")
            for q in questions[:5]
        ]) +
        ("\n..." if len(questions) > 5 else ""),
        reply_markup=questions_menu(),
    )
    await state.set_state(AdminQuestionsStates.menu)


@router.message(AdminQuestionsStates.waiting_docx_ai)
async def process_docx_ai(message: Message, state: FSMContext, session: AsyncSession) -> None:
    file_path = await _download_docx(message)
    if not file_path:
        return

    status = await message.answer("🤖 AI hujjatni tahlil qilmoqda... (10-30 soniya)")

    used = "AI"
    try:
        questions = await parse_docx_with_ai(file_path)
    except Exception as e:
        logger.warning(f"AI parse xato: {e}. Oddiy parser ga o'tiladi.")
        try:
            questions = await parse_docx_questions(file_path)
            used = "oddiy parser (AI ishlamadi)"
        except Exception as e2:
            await _safe_edit(status, text=f"❌ Faylni o'qishda xato: {e2}")
            return

    if not questions:
        await _safe_edit(status, text="❌ Faylda savollar topilmadi. Formatni tekshiring.")
        return

    count = await _save_questions(session, questions)

    await _safe_edit(
        status,
        text=f"✅ {count} ta savol yuklandi ({used}).\n\n" +
        "\n".join([
            f"• Bölüm {q['section']}-{q['order_num']}: "
            + (f"[🖼 x{(q.get('image_path') or '').count('|') + 1}] " if q.get('image_path') else "")
            + (q['text'][:50] or "(rasm savoli)")
            for q in questions[:5]
        ]) +
        ("\n..." if len(questions) > 5 else ""),
        reply_markup=questions_menu(),
    )
    await state.set_state(AdminQuestionsStates.menu)


@router.callback_query(F.data == "list_questions")
async def list_questions_handler(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    questions = await get_all_questions(session)

    if not questions:
        await _safe_edit(callback.message, text="📋 Hozircha savollar yo'q.\n\n"
            "➕ Savol kiritish tugmasini bosing.",
            reply_markup=questions_menu(),
        )
        await callback.answer()
        return

    text = f"📋 Jami savollar: {len(questions)} ta\n\n"

    current_section = None
    for q in questions:
        if q.section != current_section:
            current_section = q.section
            text += f"\n<b>📚 Bölüm {current_section}</b>\n"

        sub_count = 0
        if q.sub_questions:
            try:
                sub_list = json.loads(q.sub_questions)
                sub_count = len(sub_list) if isinstance(sub_list, list) else 0
            except (json.JSONDecodeError, ValueError, TypeError):
                sub_count = 0

        sub = f" (+{sub_count} ta)" if sub_count > 0 else ""
        text += f"  {q.order_number}. {q.text[:60]}{sub} ({q.preparation_seconds}s/{q.answer_seconds}s)\n"

    if len(text) > 4000:
        text = text[:4000] + "\n\n..."

    await _safe_edit(
        callback.message,
        text=text,
        reply_markup=questions_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "delete_questions")
async def delete_questions_handler(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    count = await get_questions_count(session)

    await state.set_state(AdminQuestionsStates.confirm_delete)
    await _safe_edit(
        callback.message,
        text=f"⚠️ Diqqat!\n\n"
        f"Barcha savollar o'chiriladi.\n"
        f"Hozirgi savollar soni: {count} ta\n"
        f"Bu amalni ortga qaytarib bo'lmaydi.",
        reply_markup=confirm_delete_questions(),
    )
    await callback.answer()


@router.callback_query(F.data == "confirm_delete_questions")
async def confirm_delete_questions_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await delete_all_questions(session)

    await _safe_edit(
        callback.message,
        text="✅ Barcha savollar o'chirildi.",
        reply_markup=questions_menu(),
    )
    await state.set_state(AdminQuestionsStates.menu)
    await callback.answer()


@router.callback_query(F.data == "cancel_delete_questions")
async def cancel_delete_questions_handler(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await _safe_edit(
        callback.message,
        text="Amal bekor qilindi.",
        reply_markup=questions_menu(),
    )
    await state.set_state(AdminQuestionsStates.menu)
    await callback.answer()


# ==================== TEST FAOLLASHTIRISH ====================

@router.callback_query(F.data == "confirm_activate")
async def confirm_activate_handler(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    # FIX #1: Endi DB ga ham yoziladi — restart safe.
    await test_state.set_test_active(True)

    registered_users = await get_registered_users(session)
    test_settings = await get_test_settings(session)
    daily_limit = 1
    current_mode = "daily"

    if test_settings:
        current_mode = test_settings.test_mode
        if current_mode == "vip":
            daily_limit = test_settings.vip_limit

    sent_count = 0
    skipped_count = 0

    for user in registered_users:
        today_attempts = await get_user_attempt_count_today(session, user.id)

        if today_attempts >= daily_limit:
            skipped_count += 1
            continue

        try:
            await callback.bot.send_message(
                chat_id=user.telegram_id,
                text="🚀 Test boshlandi!\n\n"
                     "👇 Quyidagi tugmani bosing va testni boshlang:",
                reply_markup=webapp_keyboard(
                    settings.webapp_url,
                    chat_id=user.telegram_id,
                ),
            )
            sent_count += 1
        except Exception as e:
            logger.warning(f"Foydalanuvchiga xabar yuborib bo'lmadi {user.telegram_id}: {e}")

        # FIX #12: Broadcast throttle — Telegram flood limit'ga urmaslik uchun.
        # 100 foydalanuvchi bo'lsa 5 soniya kutish (0.05 * 100) — qabul qilinadi.
        await asyncio.sleep(_BROADCAST_INTERVAL)

    await _safe_edit(
        callback.message,
        text=f"✅ Test faollashtirildi!\n\n"
        f"📨 {sent_count} ta foydalanuvchiga xabar yuborildi.\n"
        f"⏭️ {skipped_count} ta foydalanuvchi limit tugagani uchun o'tkazib yuborildi.",
        reply_markup=activate_test_keyboard(is_active=True),
    )
    await callback.answer("Test faollashtirildi!")


@router.callback_query(F.data == "deactivate_test")
async def deactivate_test_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    # FIX #1: DB ga yoziladi.
    await test_state.set_test_active(False)

    await _safe_edit(
        callback.message,
        text="🛑 Test to'xtatildi.",
        reply_markup=activate_test_keyboard(is_active=False),
    )
    await callback.answer("Test to'xtatildi!")


# ==================== NATIJALAR ====================

RESULTS_PAGE_SIZE = 10


def _attempt_line(attempt, user) -> str:
    """Bitta attempt haqida 2 qatorlik xabarni tayyorlaydi."""
    status_emoji = {
        "finished": "✅",
        "processing": "⏳",
        "active": "🟢",
    }.get(attempt.status, "❔")

    name = (user.full_name or "—")[:30]
    if user.username:
        name += f" (@{user.username[:20]})"

    started = attempt.started_at.strftime("%Y-%m-%d %H:%M") if attempt.started_at else "—"
    score = f"{attempt.score}/75" if attempt.score is not None else "—"
    level = attempt.level or "—"

    return (
        f"#{attempt.id} {status_emoji} {name}\n"
        f"▒ {started} | tg:{user.telegram_id}\n"
        f"▒ Ball: {score} | Daraja: {level}"
    )


def _results_page_keyboard(offset: int, total: int) -> InlineKeyboardMarkup:
    buttons = []
    prev_offset = offset - RESULTS_PAGE_SIZE
    next_offset = offset + RESULTS_PAGE_SIZE

    if prev_offset >= 0:
        buttons.append(
            InlineKeyboardButton("⬅️ Oldingi", callback_data=f"results_page:{prev_offset}")
        )
    if next_offset < total:
        buttons.append(
            InlineKeyboardButton("Keyingi ➡️", callback_data=f"results_page:{next_offset}")
        )

    rows = [buttons] if buttons else []
    rows.append(
        [InlineKeyboardButton("🔙 Orqaga", callback_data="results")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_results_page(message: Message, session: AsyncSession, offset: int) -> None:
    rows = await get_recent_attempts(
        session,
        limit=RESULTS_PAGE_SIZE,
        offset=offset,
    )
    total = await get_attempts_count(session)

    if not rows:
        await _safe_edit(
            message,
            text="📊 Natijalar ro'yxati\n\nHozircha test attempts mavjud emas.",
            reply_markup=results_menu(),
        )
        return

    lines = [f"📊 So'nggi testlar — jami {total} ta attempt"]
    for attempt, user in rows:
        lines.append("")
        lines.append(_attempt_line(attempt, user))
        lines.append(f"<i>──────────────</i>")

    text = "\n".join(lines)
    if len(text) > 4096:
        text = text[:4093] + "..."

    try:
        await message.edit_text(
            text,
            reply_markup=_results_page_keyboard(offset, total),
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(
            text,
            reply_markup=_results_page_keyboard(offset, total),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "list_results")
async def list_results_handler(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await _show_results_page(callback.message, session, offset=0)
    await callback.answer()


@router.callback_query(F.data.startswith("results_page:"))
async def results_page_handler(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    try:
        offset = int(callback.data.split(":", 1)[1])
        offset = max(offset, 0)
    except (ValueError, IndexError):
        offset = 0

    await _show_results_page(callback.message, session, offset=offset)
    await callback.answer()


@router.callback_query(F.data == "export_all_results")
async def export_all_results_handler(callback: CallbackQuery) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    if is_in_progress():
        await callback.answer(
            "Hozir boshqa eksport jarayoni davom etmoqda, birozdan so'ng urinib ko'ring.",
            show_alert=True,
        )
        return

    await callback.answer("Eksport tayyorlanmoqda...")
    try:
        report_path = await run_admin_export_only()
    except ExportBusyError:
        await callback.message.answer("Hozir boshqa eksport jarayoni davom etmoqda.")
        return
    except Exception:
        logger.exception("Eksportda xatolik")
        await callback.message.answer("❌ Eksportda xatolik yuz berdi.")
        return

    try:
        await callback.message.answer_document(
            FSInputFile(report_path),
            caption="📊 Foydalanuvchilar va test natijalari",
        )
    except Exception:
        logger.exception("Hisobot yuborilmadi")
        await callback.message.answer("❌ Hisobot yuborishda xatolik.")
    finally:
        try:
            report_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Hisobot fayli o'chirilmadi: %s", report_path)


@router.callback_query(F.data == "search_user")
async def search_user_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await state.set_state(AdminResultsStates.search_user)
    await _safe_edit(
        callback.message,
        text="🔍 O'quvchini qidirish\n\n"
        "Telegram ID, username yoki ism yuboring:\n"
        "Masalan: @username, 123456789 yoki \"Munisa\"\n\n"
        "🔙 Bekor qilish uchun /cancel",
        reply_markup=back_button("results"),
    )
    await callback.answer()


@router.message(AdminResultsStates.search_user)
async def process_search_user(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("❌ Iltimos, qidiruv so'zini yuboring.")
        return

    users = await search_users(session, text)
    if not users:
        await message.answer(
            f"❌ \"{text[:50]}\" bo'yicha hech kim topilmadi.",
            reply_markup=results_menu(),
        )
        await state.set_state(AdminResultsStates.menu)
        return

    lines = [f"🔍 \"{text[:50]}\" bo'yicha {len(users)} ta natija:"]
    for user in users[:10]:
        attempts = await get_user_attempts(session, user.id)
        best = max(
            (a.score for a in attempts if a.score is not None),
            default=None,
        )

        header = f"\n👤 {user.full_name or '—'}"
        if user.username:
            header += f" (@{user.username})"
        lines.append(header)
        lines.append(
            f"▒ tg:{user.telegram_id} | Testlar: {len(attempts)}"
            + (f" | Eng yaxshi: {best}/75" if best is not None else "")
            + (" | ⭐ Admin" if user.is_admin else "")
        )
        for attempt in attempts[:3]:
            score = f"{attempt.score}/75" if attempt.score is not None else "—"
            lines.append(
                f"▒   #{attempt.id} {attempt.status} | {score} | {attempt.level or '—'}"
            )

    await message.answer(
        "\n".join(lines),
        reply_markup=results_menu(),
    )
    await state.set_state(AdminResultsStates.menu)


# ==================== BLOKDAN CHIQARISH ====================

@router.callback_query(F.data == "unblock_user")
async def unblock_user_handler(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await state.set_state(AdminResultsStates.unblock_user)
    await _safe_edit(
        callback.message,
        text="🔓 Foydalanuvchini blokdan chiqarish\n\n"
        "Foydalanuvchining Telegram ID sini yuboring:\n"
        "Masalan: 8834710739\n\n"
        "⚠️ Uning barcha testlari, javoblari va audio fayllari "
        "o'chiriladi — qayta topshira oladi.",
        reply_markup=back_button("results"),
    )
    await callback.answer()


@router.message(AdminResultsStates.unblock_user)
async def process_unblock_user(
    message: Message,
    session: AsyncSession,
) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❌ To'g'ri Telegram ID (faqat raqam) yuboring.")
        return

    telegram_id = int(text)
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        await message.answer(f"❌ {telegram_id} bo'yicha foydalanuvchi topilmadi.")
        return

    if user.is_admin:
        await message.answer("❌ Bu admin hisob. O'chirish mumkin emas.")
        return

    attempts = await get_user_attempts(session, user.id)
    await message.answer(
        f"👤 {user.full_name or '—'} (@{user.username or '—'})\n"
        f"tg: {user.telegram_id}\n"
        f"Testlar soni: {len(attempts)}\n\n"
        "Barcha testlari va audio fayllari o'chiriladi.\n"
        "U yangidan test topshira oladi. Davom etasizmi?",
        reply_markup=unblock_confirm_keyboard(telegram_id),
    )


@router.callback_query(F.data.startswith("unblock_confirm:"))
async def unblock_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    try:
        telegram_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Noto'g'ri telegram ID", show_alert=True)
        return

    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        await _safe_edit(
            callback.message,
            text=f"❌ {telegram_id} bo'yicha foydalanuvchi topilmadi.",
            reply_markup=results_menu(),
        )
        await state.set_state(AdminResultsStates.menu)
        await callback.answer()
        return

    deleted = await delete_user_attempts(session, user.id)

    await _safe_edit(
        callback.message,
        text=f"✅ {telegram_id} foydalanuvchi blokdan chiqarildi.\n\n"
        f"O'chirilgan testlar: {deleted['attempts']}\n"
        f"O'chirilgan audio fayllar: {deleted['files']}\n\n"
        "Endi u yangidan test topshira oladi.",
        reply_markup=results_menu(),
    )
    await state.set_state(AdminResultsStates.menu)
    await callback.answer()


@router.callback_query(F.data == "unblock_cancel")
async def unblock_cancel(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await _safe_edit(
        callback.message,
        text="Amal bekor qilindi.",
        reply_markup=results_menu(),
    )
    await state.set_state(AdminResultsStates.menu)
    await callback.answer()


@router.callback_query(F.data == "zip_audios")
async def zip_audios_handler(callback: CallbackQuery) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    audios_dir = Path(__file__).resolve().parent.parent.parent / "data" / "audios"

    if not audios_dir.exists() or not any(audios_dir.iterdir()):
        await callback.answer("Audio fayllar topilmadi!", show_alert=True)
        return

    zip_path = Path(__file__).resolve().parent.parent.parent / "data" / "exports" / "all_audios.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in audios_dir.rglob("*"):
            if file_path.is_file():
                zipf.write(file_path, file_path.relative_to(audios_dir))

    await callback.message.answer_document(
        FSInputFile(zip_path),
        caption="📦 Barcha audio fayllar",
    )
    await callback.answer()


# ==================== TOZALASH ====================

@router.callback_query(F.data == "cleanup")
async def cleanup_warning(callback: CallbackQuery) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await _safe_edit(
        callback.message,
        text="🧹 <b>Eski ma'lumotlarni tozalash</b>\n\n"
        "Quyidagi ishlar bajariladi:\n"
        "• <b>30 daqiqadan</b> ko'p 'processing' da tiqilib qolgan "
        "attemptlar <b>active</b> ga qaytariladi\n"
        "• <b>30 kundan</b> eski attemptlar, ularning javoblari va "
        "audio fayllari o'chiriladi\n"
        "• Hech qanday javobga bog'lanmagan audio fayllar o'chiriladi\n\n"
        "Davom etasizmi?",
        reply_markup=cleanup_confirm_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "cleanup_cancel")
async def cleanup_cancel(callback: CallbackQuery) -> None:
    await _safe_edit(
        callback.message,
        text="Amal bekor qilindi.",
        reply_markup=results_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "cleanup_confirm")
async def cleanup_confirm(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    result = await run_cleanup(session)

    await _safe_edit(
        callback.message,
        text="🧹 <b>Tozalash yakunlandi</b>\n\n"
        f"• Qaytarilgan tiqilib qolgan attemptlar: <b>{result['reset_stuck']}</b>\n"
        f"• O'chirilgan eski attemptlar: <b>{result['deleted_attempts']}</b>\n"
        f"• O'chirilgan audio fayllar: <b>{result['deleted_audio_files']}</b>",
        reply_markup=results_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


# ==================== ORQAGA ====================

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()

    try:
        await callback.message.edit_text(
            "👋 Admin panelga xush kelibsiz.",
            reply_markup=admin_menu(),
        )
    except Exception:
        await callback.message.answer(
            "👋 Admin panelga xush kelibsiz.",
            reply_markup=admin_menu(),
        )

    try:
        await callback.answer()
    except Exception:
        pass


# ==================== RESET DB ====================

@router.callback_query(F.data == "reset_db")
async def reset_db_warning(callback: CallbackQuery) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await _safe_edit(
        callback.message,
        text="⚠️ Diqqat!\n\n"
        "Barcha foydalanuvchilar, natijalar va audio fayllar "
        "o'chiriladi.\nBu amalni ortga qaytarib bo'lmaydi.",
        reply_markup=confirm_reset_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "reset_cancel")
async def reset_cancel(callback: CallbackQuery) -> None:
    await _safe_edit(
        callback.message,
        text="Amal bekor qilindi.",
        reply_markup=admin_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "reset_confirm")
async def reset_confirm(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await delete_all_data(session)

    await _safe_edit(
        callback.message,
        text="✅ Baza tozalandi.",
        reply_markup=admin_menu(),
    )
    await callback.answer()