import asyncio
import logging
from pathlib import Path

from app.config import settings
from app.database.database import async_session
from app.services.base_wipe import wipe_user_data
from app.services.user_report_exporter import export_users_report

logger = logging.getLogger(__name__)

# Race condition himoyasi: kunlik avto-eksport va admin qo'lda eksporti
# bir vaqtda ishlamasligi uchun yagona flag. Ikkala jarayon ham botning
# asosiy event loopida ishlaydi, shuning uchun global asyncio flag yetarli.
_in_progress = False
_progress_lock = asyncio.Lock()


class ExportBusyError(RuntimeError):
    """Boshqa eksport jarayoni davom etayotganda yuzaga keladi."""


def is_in_progress() -> bool:
    return _in_progress


async def _send_report_to_admins(report_path: Path) -> int:
    """Hisobot faylini barcha adminlarga yuboradi — TelegramSender bilan."""
    from app.services.telegram_sender import telegram_sender

    sent = 0
    for admin_id in settings.admin_id_list:
        try:
            await telegram_sender.send_document(
                chat_id=admin_id,
                document_path=report_path,
                caption="📊 Foydalanuvchilar va test natijalari",
            )
            sent += 1
            logger.info("Hisobot admin %s ga yuborildi", admin_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Hisobot admin %s ga yuborilmadi: %s", admin_id, exc)
    return sent


async def _notify_admins_text(text: str) -> None:
    """Adminlarga matn xabar yuboradi — TelegramSender bilan."""
    from app.services.telegram_sender import telegram_sender

    for admin_id in settings.admin_id_list:
        try:
            await telegram_sender.send_message(chat_id=admin_id, text=text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Xabar admin %s ga yuborilmadi: %s", admin_id, exc)


async def run_daily_export_and_wipe() -> dict | None:
    """Har kuni 00:00 da chaqiriladi.

    1. BARCHA foydalanuvchilar va test natijalarini .docx hisobotga eksport qiladi.
    2. Adminlarning KAMIDA BITTASIGA muvaffaqiyatli yuborilishi sharti bilan
       (admin_id_list bo'sh bo'lmasa va kamida 1 ta yuborilsa) bazani
       `wipe_user_data` orqali TO'LIQ tozalaydi (users, attempts, answers,
       questions, test_settings, audio fayllar — 0 qoldirmaydi).
    3. Tozalash muvaffaqiyatli bo'lsa — yuborilgan faylni o'chiradi.
       Tozalash muvaffaqiyatsiz bo'lsa — fayl saqlanib qoladi (zaxira nusxa).

    Qaytaradi: wipe natijasi (dict) yoki wipe sodir bo'lmagan bo'lsa None.
    """
    global _in_progress
    if _in_progress:
        logger.info("Eksport allaqachon davom etmoqda — kunlik jarayon o'tkazib yuborildi")
        return None

    async with _progress_lock:
        _in_progress = True
        report_path: Path | None = None
        try:
            async with async_session() as session:
                report_path = await export_users_report(session)

            # Xavfsizlik 1: admin ro'yxati bo'sh bo'lsa — wipe bajarilmaydi.
            if not settings.admin_id_list:
                logger.error("admin_id_list bo'sh — wipe bajarilmaydi, fayl saqlanadi")
                return None

            sent = await _send_report_to_admins(report_path)

            # Xavfsizlik 2: hech bo'lmaganda bitta admin faylni olmagan bo'lsa —
            # wipe bajarilmaydi, fayl saqlanadi (baza ma'lumoti yagona manba bo'lib qoladi).
            if sent < 1:
                logger.error(
                    "Eksport hech bir admin olishmadi (sent=%s) — wipe bajarilmaydi",
                    sent,
                )
                return None

            # Kamida bitta admin faylni oldi — endi tozalash mumkin.
            try:
                async with async_session() as wipe_session:
                    wiped = await wipe_user_data(wipe_session)
            except Exception:  # noqa: BLE001
                logger.exception("Tozalash muvaffaqiyatsiz — fayl saqlanadi")
                await _notify_admins_text(
                    "⚠️ Tozalash muvaffaqiyatsiz bo'ldi. Hisobot fayli saqlanib qoldi."
                )
                raise

            # Wipe muvaffaqiyatli — yuborilgan faylni o'chiramiz (endi eskirgan).
            try:
                report_path.unlink(missing_ok=True)
                logger.info("Eski hisobot fayli o'chirildi: %s", report_path)
            except OSError:
                logger.warning("Hisobot fayli o'chirilmadi: %s", report_path)

            await _notify_admins_text(
                "✅ Kunlik hisobot yuborildi va baza to'liq tozalandi "
                "(users={users}, attempts={attempts}, answers={answers}, "
                "questions={questions}, test_settings={test_settings}, "
                "audio={audio_files}).".format(**wiped)
            )
            return wiped

        finally:
            _in_progress = False


async def run_admin_export_only() -> Path:
    """Admin qo'lda eksporti (wipe'siz). Faqat hisobot faylini yaratadi va
    yo'lini qaytaradi; yuborish va faylni o'chirishni chaqiruvchi (handler)
    bajaradi. Race bo'lsa ExportBusyError ko'tariladi."""
    global _in_progress
    if _in_progress:
        raise ExportBusyError("Hozir boshqa eksport jarayoni davom etmoqda")

    async with _progress_lock:
        if _in_progress:
            raise ExportBusyError("Hozir boshqa eksport jarayoni davom etmoqda")
        _in_progress = True
        try:
            async with async_session() as session:
                return await export_users_report(session)
        finally:
            _in_progress = False
