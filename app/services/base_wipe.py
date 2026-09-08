import logging
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Answer, TestAttempt, User
from app.services.user_scope import _USER_SELECTION
from app.utils.helpers import utcnow

logger = logging.getLogger(__name__)


def _delete_files(paths: list[str]) -> int:
    """Fayllarni o'chirib, qancha muvaffaqiyatli o'chirilganini qaytaradi."""
    deleted = 0
    for path in paths:
        try:
            file = Path(path)
            if file.exists() and file.is_file():
                file.unlink()
                deleted += 1
        except OSError:
            logger.warning("Fayl o'chirilmadi: %s", path)
    return deleted


async def _scoped_user_ids(session: AsyncSession) -> list[int]:
    """O'chiriladigan foydalanuvchi IDlari.

    Eksport hisoboti va tozalash (wipe) orasida YAGONA mezon ishlatiladi:
    `_USER_SELECTION()` — `is_admin=False` va `is_registered=True`.
    Shuning uchun adminlar va ro'yxatdan o'tmagan foydalanuvchilar wipe'dan
    chetda qoladi. `questions` va `test_settings` SAQLANADI.
    """
    result = await session.execute(select(User.id).where(_USER_SELECTION()))
    return list(result.scalars().all())


async def _scoped_attempt_ids(session: AsyncSession, user_ids: list[int]) -> list[int]:
    """Berilgan foydalanuvchilarga tegishli attempt IDlari."""
    result = await session.execute(
        select(TestAttempt.id).where(TestAttempt.user_id.in_(user_ids))
    )
    return list(result.scalars().all())


async def count_rows(session: AsyncSession) -> dict[str, int]:
    """Tozalash (wipe) amalga oshsa qancha qator o'chishini ko'rsatadigan
    hisobot. HECH NARSA O'CHIRMAYDI — faqat sanaydi."""
    user_ids = await _scoped_user_ids(session)
    attempt_ids = await _scoped_attempt_ids(session, user_ids) if user_ids else []

    answers = 0
    if attempt_ids:
        answers = (
            await session.execute(
                select(func.count(Answer.id)).where(Answer.attempt_id.in_(attempt_ids))
            )
        ).scalar_one()

    return {
        "users": len(user_ids),
        "attempts": len(attempt_ids),
        "answers": int(answers),
    }


async def wipe_user_data(session: AsyncSession) -> dict[str, Any]:
    """BARCHA foydalanuvchilarni (admin va unregistered ham), ularning test
    attemptlari va javoblarini o'chiradi.

    `questions` va `test_settings` SAQLANADI.

    Qaytaradi: {users, attempts, answers, audio_files, at} — o'chirilgan
    amallar soni hisoboti.
    """
    user_ids = await _scoped_user_ids(session)
    result = {
        "users": len(user_ids),
        "attempts": 0,
        "answers": 0,
        "audio_files": 0,
        "at": utcnow(),
    }

    if not user_ids:
        logger.info("Wipe: o'chiriladigan foydalanuvchi topilmadi")
        return result

    attempt_ids = await _scoped_attempt_ids(session, user_ids)
    result["attempts"] = len(attempt_ids)

    # Javoblarni o'chirishdan AVVAL audio fayllar yo'llarini yig'ib olamiz.
    audio_paths: list[str] = []
    if attempt_ids:
        audio_res = await session.execute(
            select(Answer.audio_path).where(Answer.attempt_id.in_(attempt_ids))
        )
        audio_paths = [p for (p,) in audio_res.all() if p]

        answers = (
            await session.execute(
                select(func.count(Answer.id)).where(Answer.attempt_id.in_(attempt_ids))
            )
        ).scalar_one()
        result["answers"] = int(answers)

    # Bog'lanish tartibi bo'yicha o'chirish: answers -> attempts -> users.
    if attempt_ids:
        await session.execute(delete(Answer).where(Answer.attempt_id.in_(attempt_ids)))
    await session.execute(delete(TestAttempt).where(TestAttempt.user_id.in_(user_ids)))
    await session.execute(delete(User).where(User.id.in_(user_ids)))

    await session.commit()

    result["audio_files"] = _delete_files(audio_paths)
    logger.info(
        "Wipe tugallandi: %s user, %s attempt, %s answer, %s audio fayl",
        result["users"], result["attempts"], result["answers"], result["audio_files"],
    )
    return result
