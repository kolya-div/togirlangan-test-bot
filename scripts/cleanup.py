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
        print("DRY-RUN rejimi: hech narsa o'chirilmaydi.\n")
        async with SessionLocal() as session:
            stuck = await cleanup_service.reset_stuck_processing(session)
            old = await cleanup_service.delete_old_attempts(session)
            orphan = await cleanup_service.delete_orphan_audios(session)
        print(f"Qaytariladi (processing->active): {stuck}")
        print(f"O'chiriladigan eski attemptlar: {old['attempts']}")
        print(f"O'chiriladigan audio fayllar: {old['files'] + orphan}")
    else:
        async with SessionLocal() as session:
            result = await cleanup_service.run_cleanup(session)
        print("Tozalash yakunlandi:")
        for key, value in result.items():
            print(f"  • {key}: {value}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())