import logging
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Answer, Question, TestAttempt, TestSettings, User
from app.services.audio_archive import (
    archive_attempt_audios,
    archive_question_images,
    new_archive_dir,
)
from app.utils.helpers import utcnow

logger = logging.getLogger(__name__)


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
    Audio fayllar o'chirilmaydi — data/archive/<sana>_kunlik/ ga ko'chiriladi,
    savol rasmlarining nusxasi ham shu yerga olinadi.

    BU TOZALASHDAN OLDIN .docx EKSPORT QILINIShI SHART (daily_export_wipe
    kafolatlaydi: kamida bitta admin faylni olmasa wipe bajarilmaydi).

    Qaytaradi: {users, attempts, answers, questions, test_settings,
    audio_files, images, archive_dir, at} — hisobot (audio_files —
    arxivga ko'chirilgan audio soni).
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

    # Audio fayllar O'CHIRILMAYDI — javoblar o'chirilishidan AVVAL
    # sana/foydalanuvchi bo'yicha arxivga ko'chiriladi, savol rasmlarining
    # nusxasi ham olinadi (qarang: audio_archive).
    archive_dir = new_archive_dir("kunlik")
    result["audio_files"] = await archive_attempt_audios(session, archive_dir)
    result["images"] = archive_question_images(archive_dir)
    result["archive_dir"] = str(archive_dir)

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

    logger.info(
        "Wipe tugallandi: %s user, %s attempt, %s answer, %s question, "
        "%s test_settings, %s audio arxivlandi",
        result["users"], result["attempts"], result["answers"],
        result["questions"], result["test_settings"], result["audio_files"],
    )
    return result