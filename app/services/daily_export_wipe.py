import asyncio
import logging
from pathlib import Path

from app.config import settings
from app.database.database import async_session
from app.services.base_wipe import wipe_user_data
from app.services.user_report_exporter import export_users_reports

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


async def _send_report_to_admins(report_paths: list[Path]) -> int:
    """Hisobot fayllarini (Word + Excel) barcha adminlarga yuboradi.

    Qaytaradi: Word hisobotni (birinchi fayl) HAQIQATAN olgan adminlar soni.
    send_document xatoda exception emas, False qaytaradi — shuning uchun
    natija tekshiriladi (oldin yuborilmasa ham "yuborildi" deb sanalardi
    va wipe bajarilib ketishi mumkin edi).
    """
    from app.services.telegram_sender import telegram_sender

    captions = {
        ".docx": "📊 Test natijalari (Word)",
        ".xlsx": "📈 Test natijalari (Excel)",
    }
    sent = 0
    for admin_id in settings.admin_id_list:
        got_main = False
        for i, path in enumerate(report_paths):
            try:
                ok = await telegram_sender.send_document(
                    chat_id=admin_id,
                    document_path=path,
                    caption=captions.get(path.suffix, "📊 Test natijalari"),
                )
            except Exception as exc:  # noqa: BLE001
                ok = False
                logger.warning("Hisobot %s admin %s ga yuborilmadi: %s", path.name, admin_id, exc)
            if ok and i == 0:
                got_main = True
        if got_main:
            sent += 1
            logger.info("Hisobot admin %s ga yuborildi", admin_id)
        else:
            logger.warning("Hisobot admin %s ga yetib bormadi", admin_id)
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
       questions, test_settings). Audio fayllar va savol rasmlari
       o'chirilmaydi — data/archive/ ga saqlanadi.
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
        try:
            async with async_session() as session:
                report_paths = await export_users_reports(session)

            # Xavfsizlik 1: admin ro'yxati bo'sh bo'lsa — wipe bajarilmaydi.
            if not settings.admin_id_list:
                logger.error("admin_id_list bo'sh — wipe bajarilmaydi, fayl saqlanadi")
                return None

            sent = await _send_report_to_admins(report_paths)

            # Xavfsizlik 2: hech bo'lmaganda bitta admin faylni olmagan bo'lsa —
            # wipe bajarilmaydi, fayl saqlanadi (baza ma'lumoti yagona manba bo'lib qoladi).
            if sent < 1:
                logger.error(
                    "Eksport hech bir admin olishmadi (sent=%s) — wipe bajarilmaydi",
                    sent,
                )
                return None

            # Kunlik hisobot hamma natijani o'z ichiga oladi — kutilayotgan
            # avtomatik hisobot (auto_report) endi kerak emas.
            from app.services import auto_report
            auto_report.mark_reported()

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

            # Wipe muvaffaqiyatli — yuborilgan fayllarni o'chiramiz (eskirgan).
            for path in report_paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Hisobot fayli o'chirilmadi: %s", path)

            await _notify_admins_text(
                "✅ Kunlik hisobot yuborildi va baza tozalandi "
                "(users={users}, attempts={attempts}, answers={answers}, "
                "questions={questions}, test_settings={test_settings}).\n"
                "🎧 {audio_files} ta audio va {images} ta savol rasmi "
                "arxivda saqlandi: {archive_dir}".format(**wiped)
            )
            return wiped

        finally:
            _in_progress = False


async def run_admin_export_only() -> list[Path]:
    """Admin qo'lda eksporti (wipe'siz). Word va Excel hisobotlarni yaratib,
    yo'llarini qaytaradi; yuborish va fayllarni o'chirishni chaqiruvchi
    (handler) bajaradi. Race bo'lsa ExportBusyError ko'tariladi."""
    global _in_progress
    if _in_progress:
        raise ExportBusyError("Hozir boshqa eksport jarayoni davom etmoqda")

    async with _progress_lock:
        if _in_progress:
            raise ExportBusyError("Hozir boshqa eksport jarayoni davom etmoqda")
        _in_progress = True
        try:
            async with async_session() as session:
                return await export_users_reports(session)
        finally:
            _in_progress = False
