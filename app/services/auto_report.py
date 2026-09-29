"""AI barcha javoblarni tekshirib bo'lgach — natijalarni (Word + Excel)
adminlarga avtomatik yuborish.

Har bir attempt baholangach `notify_attempt_evaluated()` chaqiriladi.
Hisobot darhol emas, AUTO_REPORT_DELAY_SECONDS jimlikdan keyin yuboriladi
(debounce): odamlar testni turli vaqtda tugatadi — har biri uchun alohida
fayl yubormaslik uchun, yangi baholash kelsa kutish qaytadan boshlanadi.
Yuborishdan oldin navbat bo'shligi va bazada "processing" qolmagani
tekshiriladi; aks holda yana kutiladi.
"""

import asyncio
import logging

from sqlalchemy import func, select

from app.config import settings

logger = logging.getLogger(__name__)

_timer: asyncio.Task | None = None
_evaluated_since_report = 0


def _delay() -> float:
    return float(getattr(settings, "auto_report_delay_seconds", 180))


def notify_attempt_evaluated() -> None:
    """Bitta attempt AI baholashdan o'tdi — hisobot taymerini qayta boshlaydi."""
    global _evaluated_since_report
    if not getattr(settings, "auto_report_enabled", True):
        return
    _evaluated_since_report += 1
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
        await send_auto_report()
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

    queue = report_worker._report_queue
    if report_worker._pending_attempts or (queue is not None and not queue.empty()):
        return False
    return (await _counts())["processing"] == 0


async def send_auto_report() -> bool:
    """Word + Excel hisobotni adminlarga yuboradi. Yuborilsa True."""
    global _evaluated_since_report
    from app.services.daily_export_wipe import (
        ExportBusyError,
        _notify_admins_text,
        _send_report_to_admins,
        run_admin_export_only,
    )

    if _evaluated_since_report == 0:
        return False  # oxirgi hisobotdan beri yangi natija yo'q

    try:
        paths = await run_admin_export_only()
    except ExportBusyError:
        _restart_timer()  # boshqa eksport ketmoqda — keyinroq
        return False

    try:
        counts = await _counts()
        text = (
            "🤖 <b>AI javoblarni tekshirib bo'ldi</b>\n\n"
            f"✅ Tekshirilgan testlar: <b>{counts['finished']}</b>\n"
        )
        if counts["active"]:
            text += f"⏳ Hali tugatmaganlar: <b>{counts['active']}</b>\n"
        text += "\nNatijalar (Word va Excel) quyida 👇"
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
        logger.info("Avtomatik hisobot %s ta adminga yuborildi", sent)
    return bool(sent)


def mark_reported() -> None:
    """Natijalar boshqa yo'l bilan (kunlik 00:00 hisobot) yuborildi —
    kutilayotgan avtomatik hisobot kerak emas."""
    global _timer, _evaluated_since_report
    _evaluated_since_report = 0
    if _timer is not None and not _timer.done():
        _timer.cancel()
    _timer = None


async def stop() -> None:
    global _timer
    if _timer is not None and not _timer.done():
        _timer.cancel()
    _timer = None
