import logging
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Answer, TestAttempt
from app.utils.helpers import utcnow

logger = logging.getLogger(__name__)

# Qayta ishlanmoqda ("processing") holatida bu vaqtdan ko'proq turgan
# attemptlar "active" ga qaytariladi (user testni davom ettira oladi).
PROCESSING_STALE_MINUTES = 30

# Bu vaqtdan eski yakunlangan/tugallanmagan attemptlar (javoblari va
# audio fayllari bilan birga) o'chiriladi.
DELETE_OLDER_DAYS = 30


async def reset_stuck_processing(session: AsyncSession) -> int:
    """Serverni qayta ishga tushirishdan keyin tiqilib qolgan
    'processing' attemptlarni 'active' holatiga qaytaradi."""
    stale_before = utcnow() - timedelta(minutes=PROCESSING_STALE_MINUTES)
    result = await session.execute(
        select(TestAttempt).where(
            TestAttempt.status == "processing",
            TestAttempt.finished_at < stale_before,
        )
    )
    stuck = list(result.scalars().all())
    for attempt in stuck:
        attempt.status = "active"
    logger.info("Stuck processing attempts reset to active: %s", [a.id for a in stuck])
    return len(stuck)


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
    """Hech qanday javobga bog'lanmagan audio fayllarni o'chirish."""
    audio_res = await session.execute(select(Answer.audio_path).where(Answer.audio_path.isnot(None)))
    referenced = {str(path) for (path,) in audio_res.all()}
    referenced = {p.replace("\\", "/") for p in referenced}

    audios_dir = Path(settings.upload_dir)
    orphan_paths = []
    if audios_dir.exists():
        for file in audios_dir.rglob("*"):
            if file.is_file():
                relative = str(file).replace("\\", "/")
                if relative not in referenced:
                    orphan_paths.append(str(file))

    deleted = _delete_files(orphan_paths)
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


async def run_cleanup(session: AsyncSession) -> dict:
    """Barcha tozalash ishlarini bajarib, natija hisobini qaytaradi."""
    reset_count = await reset_stuck_processing(session)
    old_result = await delete_old_attempts(session)
    orphan_files = await delete_orphan_audios(session)

    await session.commit()

    return {
        "reset_stuck": reset_count,
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