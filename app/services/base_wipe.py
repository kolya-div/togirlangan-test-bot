import logging
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Answer, Question, TestAttempt, TestSettings, User
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


async def count_rows(session: AsyncSession) -> dict[str, int]:
    """Tozalash (wipe) amalga oshsa qancha qator o'chishini ko'rsatadigan
    hisobot. HECH NARSA O'CHIRMAYDI — faqat sanaydi."""
    async def _count(model) -> int:
        return (
            await session.execute(select(func.count()).select_from(model))
        ).scalar_one()

    answers = await _count(Answer)
    attempts = await _count(TestAttempt)
    return {
        "users": await _count(User),
        "attempts": attempts,
        "answers": answers,
        "questions": await _count(Question),
        "test_settings": await _count(TestSettings),
    }


async def wipe_user_data(session: AsyncSession) -> dict[str, Any]:
    """BAZA TO'LIQ TOZALAYDI — 0 QOLDIRMAYDIGAN WIPE.

    Barcha jadvallar bo'shatiladi:
      - users, test_attempts, answers (foydalanuvchi va test ma'lumoti)
      - questions (savol bazasi — admin yangilarini yuklaydi)
      - test_settings (test holati/is_active/invite_token)
    Qo'shimcha: barcha audio fayllar ham o'chiriladi.

    BU TOZALASHDAN OLDIN .docx EKSPORT QILINIShI SHART (daily_export_wipe
    kafolatlaydi: kamida bitta admin faylni olmasa wipe bajarilmaydi).

    Qaytaradi: {users, attempts, answers, questions, test_settings,
    audio_files, at} — o'chirilgan amallar soni hisoboti.
    """
    result = {
        "users": 0,
        "attempts": 0,
        "answers": 0,
        "questions": 0,
        "test_settings": 0,
        "audio_files": 0,
        "at": utcnow(),
    }

    # Javoblarni o'chirishdan AVVAL audio fayllar yo'llarini yig'ib olamiz.
    audio_res = await session.execute(select(Answer.audio_path))
    audio_paths = [p for (p,) in audio_res.all() if p]

    result["users"] = (
        await session.execute(select(func.count()).select_from(User))
    ).scalar_one()
    result["attempts"] = (
        await session.execute(select(func.count()).select_from(TestAttempt))
    ).scalar_one()
    result["answers"] = (
        await session.execute(select(func.count()).select_from(Answer))
    ).scalar_one()
    result["questions"] = (
        await session.execute(select(func.count()).select_from(Question))
    ).scalar_one()
    result["test_settings"] = (
        await session.execute(select(func.count()).select_from(TestSettings))
    ).scalar_one()

    # Bog'liqliklar bo'yicha o'chirish tartibi.
    await session.execute(delete(Answer))
    await session.execute(delete(TestAttempt))
    await session.execute(delete(User))
    await session.execute(delete(Question))
    await session.execute(delete(TestSettings))

    await session.commit()

    result["audio_files"] = _delete_files(audio_paths)
    logger.info(
        "Wipe tugallandi: %s user, %s attempt, %s answer, %s question, "
        "%s test_settings, %s audio fayl",
        result["users"], result["attempts"], result["answers"],
        result["questions"], result["test_settings"], result["audio_files"],
    )
    return result