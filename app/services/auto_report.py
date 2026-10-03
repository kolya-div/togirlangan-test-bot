"""AI barcha javoblarni tekshirib bo'lgach — adminlardan so'rash:
"Javoblar tayyor. Yana testdan o'tadiganlar bormi?"  [✅ Ha] [❌ Yo'q]

- Yo'q → natijalar (Word + Excel) adminlarga yuboriladi.
- Ha   → admin panel tugmalari; keyingi testlar tekshirilgach yana so'raladi.

Har bir attempt baholangach `notify_attempt_evaluated()` chaqiriladi.
Savol darhol emas, AUTO_REPORT_DELAY_SECONDS jimlikdan keyin yuboriladi
(debounce): odamlar testni turli vaqtda tugatadi — yangi baholash kelsa
kutish qaytadan boshlanadi. Oldin navbat bo'shligi va bazada "processing"
qolmagani tekshiriladi; aks holda yana kutiladi.
"""

import asyncio
import logging

from sqlalchemy import func, select

from app.config import settings

logger = logging.getLogger(__name__)

_timer: asyncio.Task | None = None
_evaluated_since_report = 0
# Oxirgi savoldan beri baholangan testlar. Admin oldingi savolga javob
# bermagan bo'lsa ham, yangi testlar tekshirilgach savol QAYTA yuboriladi
# (oldin javobsiz savol keyingi barcha savollarni to'sib qo'yardi).
_new_since_prompt = 0
_prompt_pending = False


def _delay() -> float:
    return float(getattr(settings, "auto_report_delay_seconds", 30))


def notify_attempt_evaluated() -> None:
    """Bitta attempt AI baholashdan o'tdi — hisobot taymerini qayta boshlaydi."""
    global _evaluated_since_report, _new_since_prompt
    if not getattr(settings, "auto_report_enabled", True):
        return
    _evaluated_since_report += 1
    _new_since_prompt += 1
    _restart_timer()


def _restart_timer() -> None:
    global _timer
    # Taymerning o'zi (yana kutish kerak bo'lganda) chaqirsa — o'zini bekor qilmaydi
    if _timer is not None and not _timer.done() and _timer is not asyncio.current_task():
        _timer.cancel()
    _timer = asyncio.get_running_loop().create_task(_wait_and_send())


async def _wait_and_send() -> None:
    try:
        await asyncio.sleep(_delay())
    except asyncio.CancelledError:
        return
    try:
        if not await _all_evaluated():
            _restart_timer()  # hali tekshirilayotganlar bor — yana kutamiz
            return
        await ask_admins()
    except Exception:
        logger.exception("Avtomatik hisobot yuborilmadi")


async def _counts() -> dict[str, int]:
    from app.database.database import SessionLocal
    from app.database.models import TestAttempt

    async with SessionLocal() as session:
        rows = (await session.execute(
            select(TestAttempt.status, func.count()).group_by(TestAttempt.status)
        )).all()
    counts = {status: n for status, n in rows}
    return {
        "finished": counts.get("finished", 0),
        "processing": counts.get("processing", 0),
        "active": counts.get("active", 0) + counts.get("started", 0),
    }


async def _all_evaluated() -> bool:
    from app.services import report_worker

    # Faqat navbat (xotira) tekshiriladi. Bazadagi "processing" holati
    # tekshirilmaydi: AI xatosi tufayli tiqilib qolgan bitta test savolni
    # butunlay to'sib qo'yardi. Restartdan keyin bunday testlar baribir
    # navbatga qaytariladi.
    queue = report_worker._report_queue
    return not report_worker._pending_attempts and (queue is None or queue.empty())


async def ask_admins() -> int:
    """"Javoblar tayyor. Yana testdan o'tadiganlar bormi?" [Ha] [Yo'q].
    Qaytaradi: savol yetkazilgan adminlar soni."""
    global _prompt_pending, _new_since_prompt
    from app.bot.bot import bot
    from app.bot.keyboards import auto_report_keyboard

    if _evaluated_since_report == 0 or _new_since_prompt == 0:
        return 0  # oxirgi savoldan beri yangi natija yo'q

    counts = await _counts()
    text = (
        "✅ <b>Barcha javoblar tayyor!</b>\n\n"
        f"AI tekshirgan testlar: <b>{counts['finished']}</b>\n"
    )
    if counts["active"]:
        text += f"⏳ Hali tugatmaganlar: <b>{counts['active']}</b>\n"
    if counts["processing"]:
        text += f"⚠️ Tekshirilmay qolganlar: <b>{counts['processing']}</b>\n"
    text += (
        "\n❓ Yana testdan o'tadiganlar bormi?\n\n"
        "«Yo'q» — natijalar (Word va Excel) hozir yuboriladi.\n"
        "«Ha» — hamma tugatgach yana so'rayman."
    )
    delivered = 0
    for admin_id in settings.admin_id_list:
        try:
            await bot.send_message(
                admin_id, text, parse_mode="HTML", reply_markup=auto_report_keyboard(),
            )
            delivered += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Admin %s ga savol yuborilmadi: %s", admin_id, exc)
    if delivered:
        _prompt_pending = True
        _new_since_prompt = 0
    return delivered


def answer_yes() -> None:
    """Admin «Ha» bosdi — hozir yubormaymiz; keyingi testlar tekshirilgach
    yana so'raymiz (yangi baholash taymerni qayta boshlaydi)."""
    global _prompt_pending
    _prompt_pending = False


async def send_auto_report(force: bool = False) -> bool:
    """Word + Excel hisobotni adminlarga yuboradi. Yuborilsa True.

    force=True — admin «Yo'q» bosganda: yangi natija bo'lmasa ham yuboriladi.
    """
    global _evaluated_since_report, _prompt_pending, _new_since_prompt
    from app.services.daily_export_wipe import (
        ExportBusyError,
        _notify_admins_text,
        _send_report_to_admins,
        run_admin_export_only,
    )

    if _evaluated_since_report == 0 and not force:
        return False  # oxirgi hisobotdan beri yangi natija yo'q

    try:
        paths = await run_admin_export_only()
    except ExportBusyError:
        if not force:
            _restart_timer()  # boshqa eksport ketmoqda — keyinroq
        return False

    try:
        counts = await _counts()
        text = (
            "📊 <b>Test natijalari</b>\n\n"
            f"✅ Tekshirilgan testlar: <b>{counts['finished']}</b>\n"
        )
        if counts["active"]:
            text += f"⏳ Hali tugatmaganlar: <b>{counts['active']}</b>\n"
        text += "\nWord va Excel fayllar quyida 👇"
        await _notify_admins_text(text)
        sent = await _send_report_to_admins(paths)
    finally:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Hisobot fayli o'chirilmadi: %s", path)

    if sent:
        _evaluated_since_report = 0
        _new_since_prompt = 0
        _prompt_pending = False
        logger.info("Natijalar hisoboti %s ta adminga yuborildi", sent)
    return bool(sent)


def mark_reported() -> None:
    """Natijalar boshqa yo'l bilan (kunlik 00:00 hisobot) yuborildi —
    kutilayotgan avtomatik hisobot kerak emas."""
    global _timer, _evaluated_since_report, _prompt_pending, _new_since_prompt
    _evaluated_since_report = 0
    _new_since_prompt = 0
    _prompt_pending = False
    if _timer is not None and not _timer.done():
        _timer.cancel()
    _timer = None


async def stop() -> None:
    global _timer
    if _timer is not None and not _timer.done():
        _timer.cancel()
    _timer = None
