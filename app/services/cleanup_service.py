import logging
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Answer, TestAttempt
from app.utils.helpers import utcnow

logger = logging.getLogger(__name__)

# Qayta ishlanmoqda ("processing") holatida bu vaqtdan ko'proq turgan va
# navbatda bo'lmagan attemptlar hisobot navbatiga QAYTA qo'shiladi.
# Navbat xotirada (asyncio.Queue) — server qayta ishga tushsa yoki navbat
# to'lib enqueue muvaffaqiyatsiz bo'lsa, attempt "processing" da qolib
# ketadi. Oldin bunday attemptlar "active" ga qaytarilardi — lekin
# create_attempt "active" ga 403 beradi, natijada foydalanuvchi na natija
# oladi, na testni qayta topshira oladi.
# Kichik zaxira: finish commit va enqueue_report orasidagi oraliq
# (navbat to'la bo'lsa ~30s retry) bilan to'qnashmaslik uchun.
PROCESSING_STALE_MINUTES = 5

# Bitta attempt necha marta qayta navbatga qo'yiladi. Worker har safar
# xato bilan tugasa, cheksiz aylanib qolmasligi uchun chegara. Chegaradan
# keyin adminlarga xabar beriladi (admin foydalanuvchini blokdan chiqaradi).
MAX_REQUEUE_ATTEMPTS = 3
_requeue_counts: dict[int, int] = {}

# Bu vaqtdan eski yakunlangan/tugallanmagan attemptlar (javoblari va
# audio fayllari bilan birga) o'chiriladi.
DELETE_OLDER_DAYS = 30

# BUG FIX: routes.py'dagi upload_answer() audio faylni avval vaqtinchalik
# nom bilan (".upload_{attempt_id}_{question_id}_...") shu papkaga yozadi
# va faqat TO'LIQ yuklanib, DB'ga answer yozuvi commit bo'lgandan keyin
# yakuniy nomga o'zgartiradi (os.replace). `Path.rglob("*")` esa nuqta
# bilan boshlangan ("yashirin") fayllarni ham qamrab oladi — shuning
# uchun agar `delete_orphan_audios` aynan kimdir audio yuklab turgan
# paytda ishga tushsa (hali DB'da answer yo'q), bu vaqtinchalik faylni
# "orphan" deb o'chirib yuborishi mumkin edi. Natijada `os.replace`
# FileNotFoundError berib, foydalanuvchining yuklashi 500 xato bilan
# muvaffaqiyatsiz tugar edi (audio qayta yozib yuborilishi kerak bo'lardi).
#
# Yechim: hali yaqinda (bu chegaradan kam vaqt oldin) o'zgargan fayllarni
# "orphan" deb hisoblamaymiz — ular hali yuklanayotgan bo'lishi mumkin.
ORPHAN_MIN_AGE_SECONDS = 600  # 10 daqiqa


async def find_stuck_processing(
    session: AsyncSession,
    stale_minutes: int = PROCESSING_STALE_MINUTES,
) -> list[int]:
    """Navbatda bo'lmagan va `stale_minutes` dan beri "processing" holatida
    turgan attempt ID lari. HECH NARSA O'ZGARTIRMAYDI."""
    from app.services.report_worker import is_pending

    stale_before = utcnow() - timedelta(minutes=stale_minutes)
    result = await session.execute(
        select(TestAttempt.id).where(
            TestAttempt.status == "processing",
            TestAttempt.finished_at < stale_before,
        )
    )
    return [aid for (aid,) in result.all() if not is_pending(aid)]


async def requeue_stuck_processing(
    session: AsyncSession,
    stale_minutes: int = PROCESSING_STALE_MINUTES,
) -> int:
    """Tiqilib qolgan "processing" attemptlarni hisobot navbatiga qayta
    qo'shadi (holat o'zgarmaydi — "processing" qoladi).

    Faqat hisobot workerlari ishlayotgan processda chaqirilishi kerak
    (navbat xotirada).
    """
    from app.services.report_worker import enqueue_report

    stuck_ids = await find_stuck_processing(session, stale_minutes)
    requeued: list[int] = []
    given_up: list[int] = []

    for attempt_id in stuck_ids:
        count = _requeue_counts.get(attempt_id, 0)
        if count >= MAX_REQUEUE_ATTEMPTS:
            # Oxirgi qayta urinish ham natija bermadi — adminga bir marta xabar.
            if count == MAX_REQUEUE_ATTEMPTS:
                _requeue_counts[attempt_id] = count + 1
                given_up.append(attempt_id)
            continue
        _requeue_counts[attempt_id] = count + 1

        answers_count = (
            await session.execute(
                select(func.count())
                .select_from(Answer)
                .where(Answer.attempt_id == attempt_id)
            )
        ).scalar() or 0
        if await enqueue_report(attempt_id, total_answers=answers_count):
            requeued.append(attempt_id)

    if requeued:
        logger.info("Stuck processing attempts requeued: %s", requeued)
    if given_up:
        await _notify_admins_requeue_limit(given_up)
    return len(requeued)


async def _notify_admins_requeue_limit(attempt_ids: list[int]) -> None:
    """Oxirgi urinishda ham qayta ishlanmasa — admin aralashuvi kerak."""
    from app.services.telegram_sender import telegram_sender

    text = (
        "⚠️ <b>Hisobot qayta ishlanmadi</b>\n\n"
        f"Attemptlar {MAX_REQUEUE_ATTEMPTS} marta qayta navbatga qo'yildi: "
        + ", ".join(f"#{aid}" for aid in attempt_ids)
        + "\nAgar natija kelmasa, foydalanuvchini blokdan chiqaring."
    )
    for admin_id in settings.admin_id_list:
        try:
            await telegram_sender.send_message(admin_id, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Admin %s ga xabar yuborilmadi: %s", admin_id, exc)


async def delete_old_attempts(session: AsyncSession) -> dict:
    """Eski attemptlarni javob va audio fayllari bilan o'chirish."""
    old_before = utcnow() - timedelta(days=DELETE_OLDER_DAYS)
    result = await session.execute(
        select(TestAttempt).where(TestAttempt.started_at < old_before)
    )
    old_attempts = list(result.scalars().all())
    ids = [a.id for a in old_attempts]

    deleted_files = 0
    if ids:
        audio_res = await session.execute(
            select(Answer.audio_path).where(Answer.attempt_id.in_(ids))
        )
        audio_paths = [path for (path,) in audio_res.all() if path]

        await session.execute(delete(Answer).where(Answer.attempt_id.in_(ids)))
        await session.execute(delete(TestAttempt).where(TestAttempt.id.in_(ids)))

        deleted_files = _delete_files(audio_paths)
        logger.info(
            "Deleted %s old attempts (%s audio refs, %s files)",
            len(ids), len(audio_paths), deleted_files,
        )

    return {
        "attempts": len(ids),
        "files": deleted_files,
    }


async def delete_orphan_audios(session: AsyncSession) -> int:
    """Hech qanday javobga bog'lanmagan audio fayllarni o'chirish.

    Race condition himoyasi: fayllarni skanerlash va o'chirish orasida
    yangi answer qo'shilishi mumkin. Shuning uchun o'chirishdan OLDIN
    qayta tekshiriladi — fayl hali ham DB'da yo'q bo'lsa va faqat
    ORPHAN_MIN_AGE_SECONDS dan eski bo'lsa o'chiriladi.
    """
    audio_res = await session.execute(select(Answer.audio_path).where(Answer.audio_path.isnot(None)))
    referenced = {str(path) for (path,) in audio_res.all()}
    referenced = {p.replace("\\", "/") for p in referenced}

    audios_dir = Path(settings.upload_dir)
    now = time.time()
    orphan_paths = []
    if audios_dir.exists():
        for file in audios_dir.rglob("*"):
            if not file.is_file():
                continue
            relative = str(file).replace("\\", "/")
            if relative in referenced:
                continue
            # Hali yuklanayotgan bo'lishi mumkin bo'lgan yangi/vaqtinchalik
            # fayllarni tegmasdan qoldiramiz (qarang: ORPHAN_MIN_AGE_SECONDS).
            try:
                age = now - file.stat().st_mtime
            except OSError:
                continue
            if age < ORPHAN_MIN_AGE_SECONDS:
                continue
            orphan_paths.append(str(file))

    # RACE CONDITION HIMoyASI: o'chirishdan oldin qayta tekshirish.
    # Bu oraliqda fayl DB'ga bog'langan bo'lishi mumkin (answer record added).
    audio_res2 = await session.execute(select(Answer.audio_path).where(Answer.audio_path.isnot(None)))
    referenced_now = {str(path) for (path,) in audio_res2.all()}
    referenced_now = {p.replace("\\", "/") for p in referenced_now}

    # Faqat hali ham DB'da bog'lanmagan fayllarni o'chiramiz
    still_orphan = [p for p in orphan_paths if p.replace("\\", "/") not in referenced_now]

    deleted = _delete_files(still_orphan)
    if len(orphan_paths) != len(still_orphan):
        logger.info(
            "Orphan scan: %d found, %d re-verified, %d deleted (race saved %d)",
            len(orphan_paths), len(still_orphan), deleted,
            len(orphan_paths) - len(still_orphan),
        )
    else:
        logger.info("Deleted %s orphan audio files", deleted)
    return deleted


def _delete_files(paths: list[str]) -> int:
    deleted = 0
    for path in paths:
        try:
            file = Path(path)
            if file.exists() and file.is_file():
                file.unlink()
                deleted += 1
        except OSError:
            logger.warning("Could not delete file: %s", path)
    return deleted


async def run_cleanup(session: AsyncSession, requeue: bool = True) -> dict:
    """Barcha tozalash ishlarini bajarib, natija hisobini qaytaradi.

    requeue=False — alohida processdan (scripts/cleanup.py) chaqirilganda:
    u yerda hisobot navbati yo'q, shuning uchun faqat sanaladi.
    """
    if requeue:
        stuck_count = await requeue_stuck_processing(session)
    else:
        stuck_count = len(await find_stuck_processing(session))
    old_result = await delete_old_attempts(session)
    orphan_files = await delete_orphan_audios(session)

    await session.commit()

    return {
        "requeued_stuck": stuck_count,
        "deleted_attempts": old_result["attempts"],
        "deleted_audio_files": old_result["files"] + orphan_files,
    }


async def delete_user_attempts(
    session: AsyncSession,
    user_id: int,
) -> dict:
    """Foydalanuvchining barcha attemptlarini (javob va audio bilan) o'chirish.

    Blokdan chiqarish uchun ishlatiladi — keyin foydalanuvchi
    yangidan test topshira oladi.
    """
    result = await session.execute(
        select(TestAttempt).where(TestAttempt.user_id == user_id)
    )
    attempts = list(result.scalars().all())
    ids = [a.id for a in attempts]

    deleted_files = 0
    if ids:
        audio_res = await session.execute(
            select(Answer.audio_path).where(Answer.attempt_id.in_(ids))
        )
        audio_paths = [path for (path,) in audio_res.all() if path]

        await session.execute(delete(Answer).where(Answer.attempt_id.in_(ids)))
        await session.execute(delete(TestAttempt).where(TestAttempt.id.in_(ids)))
        deleted_files = _delete_files(audio_paths)

        logger.info(
            "Deleted %s attempts for user %s (%s audio files)",
            len(ids), user_id, deleted_files,
        )

    await session.commit()

    return {
        "attempts": len(ids),
        "files": deleted_files,
    }