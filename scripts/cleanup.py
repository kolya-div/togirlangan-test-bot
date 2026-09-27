"""Eski ma'lumotlarni tozalash skripti.

Ishlatish:
    python scripts/cleanup.py            # tozalashni bajarish
    python scripts/cleanup.py --dry-run  # faqat nima bo'lishini ko'rsatish
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.database import SessionLocal, engine  # noqa: E402
from app.services import cleanup_service  # noqa: E402


async def main() -> None:
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        # Faqat sanaydi: fayllar va DB ga tegmaydi (oldin delete_* chaqirilib,
        # dry-run'da ham audio fayllar haqiqatan o'chirilardi).
        from datetime import timedelta

        from sqlalchemy import func, select

        from app.database.models import TestAttempt
        from app.utils.helpers import utcnow

        async with SessionLocal() as session:
            stuck = len(await cleanup_service.find_stuck_processing(session))
            old_before = utcnow() - timedelta(days=cleanup_service.DELETE_OLDER_DAYS)
            old = (await session.execute(
                select(func.count()).select_from(TestAttempt)
                .where(TestAttempt.started_at < old_before)
            )).scalar()
        print(f"Tiqilib qolgan (processing) attemptlar: {stuck}")
        print(f"O'chiriladigan eski attemptlar (audio arxivga olinadi): {old}")
    else:
        async with SessionLocal() as session:
            # Alohida process — hisobot navbati yo'q, stuck attemptlar
            # faqat sanaladi (ular botning o'zida qayta navbatga qo'yiladi).
            result = await cleanup_service.run_cleanup(session, requeue=False)
        print("Tozalash yakunlandi:")
        for key, value in result.items():
            print(f"  • {key}: {value}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())