"""Audio javoblar va savol rasmlarini arxivlash.

Baza tozalanganda (kunlik wipe, blokdan chiqarish, eski testlar) audio
fayllar O'CHIRILMAYDI — sana va foydalanuvchi bo'yicha arxivga ko'chiriladi:

    data/archive/2026-09-27_0000_kunlik/
        Ali_Valiyev_860103732/1.1-1.webm
        Ali_Valiyev_860103732/1.4-1.webm
        savol_rasmlari/rId4.png

Arxiv data/audios dan tashqarida — "yetim audio" tozalashi unga tegmaydi.
"""

import logging
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Answer, Question, TestAttempt, User
from app.utils.helpers import format_filename, local_now

logger = logging.getLogger(__name__)


def archive_root() -> Path:
    return Path(settings.upload_dir).parent / "archive"


def new_archive_dir(label: str) -> Path:
    """Yangi arxiv papkasi yo'li: <root>/<sana_vaqt>_<label> (yaratilmaydi)."""
    stamp = local_now().strftime("%Y-%m-%d_%H%M")
    base = archive_root() / f"{stamp}_{label}"
    path, n = base, 2
    while path.exists():
        path = base.with_name(f"{base.name}_{n}")
        n += 1
    return path


def _user_folder(full_name: str | None, telegram_id: int) -> str:
    name = format_filename((full_name or "").strip().replace(" ", "_"))
    return f"{name}_{telegram_id}" if name else str(telegram_id)


async def archive_attempt_audios(
    session: AsyncSession,
    dest: Path,
    attempt_ids: list[int] | None = None,
) -> int:
    """Attemptlar (None — hammasi) audio javoblarini `dest` ga ko'chiradi.

    DB yozuvlarini O'ZGARTIRMAYDI — chaqiruvchi keyin o'chiradi.
    Qaytaradi: ko'chirilgan fayllar soni.
    """
    query = (
        select(
            Answer.id, Answer.audio_path,
            User.full_name, User.telegram_id,
            Question.section, Question.order_number,
        )
        .join(TestAttempt, Answer.attempt_id == TestAttempt.id)
        .join(User, TestAttempt.user_id == User.id)
        .join(Question, Answer.question_id == Question.id, isouter=True)
        .where(Answer.audio_path.isnot(None))
    )
    if attempt_ids is not None:
        if not attempt_ids:
            return 0
        query = query.where(Answer.attempt_id.in_(attempt_ids))

    moved = 0
    for answer_id, audio_path, full_name, tg_id, section, order in (await session.execute(query)).all():
        src = Path(audio_path)
        if not src.is_file():
            continue
        folder = dest / _user_folder(full_name, tg_id)
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{section}-{order}" if section else f"javob-{answer_id}"
        target = folder / f"{stem}{src.suffix}"
        if target.exists():
            target = folder / f"{stem}_{answer_id}{src.suffix}"
        try:
            shutil.move(str(src), str(target))
            moved += 1
        except OSError:
            logger.warning("Audio arxivga ko'chirilmadi: %s", src)
    if moved:
        logger.info("%s ta audio arxivlandi: %s", moved, dest)
    return moved


def archive_question_images(dest: Path) -> int:
    """Savol rasmlarining NUSXASINI `dest/savol_rasmlari` ga oladi.

    Nusxa — chunki joriy savollar ularni hali ishlatadi; keyingi docx
    yuklanganda bir xil nomli (rId4.png ...) fayllar ustidan yoziladi.
    """
    images_dir = Path(settings.upload_dir) / "images"
    if not images_dir.is_dir():
        return 0
    files = [f for f in images_dir.iterdir() if f.is_file()]
    if not files:
        return 0
    target = dest / "savol_rasmlari"
    target.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, target / f.name)
    return len(files)
