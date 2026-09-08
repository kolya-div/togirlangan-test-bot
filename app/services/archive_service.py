import zipfile
from pathlib import Path
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Answer, TestAttempt, User


async def create_zip_archive(
    session: AsyncSession,
    output_path: str,
) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    result = await session.execute(
        select(Answer)
        .join(TestAttempt)
        .join(User)
        .order_by(User.full_name, TestAttempt.started_at),
    )
    answers = result.scalars().all()

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for answer in answers:
            if answer.audio_path and Path(answer.audio_path).exists():
                archive.write(
                    answer.audio_path,
                    f"audios/{Path(answer.audio_path).name}",
                )

    return str(output)