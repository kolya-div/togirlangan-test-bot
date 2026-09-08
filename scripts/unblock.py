"""Foydalanuvchini blokdan chiqarish skripti.

Foydalanuvchining barcha attemptlarini (javob va audio bilan) o'chiradi —
keyin u yangidan test topshira oladi.

Ishlatish:
    python scripts/unblock.py --user 8834710739
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select  # noqa: E402

from app.database.database import SessionLocal, engine  # noqa: E402
from app.database.models import User  # noqa: E402
from app.services.cleanup_service import delete_user_attempts  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True, type=int, help="Telegram ID")
    args = parser.parse_args()

    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == args.user)
        )
        user = result.scalar_one_or_none()

        if not user:
            print(f"❌ {args.user} bo'yicha foydalanuvchi topilmadi.")
            return

        print(
            f"👤 {user.full_name or '—'} (@{user.username or '—'}) tg:{user.telegram_id}"
        )
        deleted = await delete_user_attempts(session, user.id)
        print(
            f"✅ Blokdan chiqarildi: {deleted['attempts']} test va "
            f"{deleted['files']} audio o'chirildi."
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())