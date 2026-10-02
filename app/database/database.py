import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# Connection pool: NullPool o'rniga real pool ishlatiladi.
# Pool size + max_overflow — 100+ user uchun yetarli zaxira.
# webapp (30) + report workers (10) + bot (15) + zahira (15) = ~60 max.
# O'lchamlar database.py config'da: DB_POOL_SIZE / DB_MAX_OVERFLOW.
pool_size = max(20, getattr(settings, "db_pool_size", 30))
max_overflow = max(20, getattr(settings, "db_max_overflow", 30))

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=pool_size,
    max_overflow=max_overflow,
    pool_timeout=30,
    pool_pre_ping=True,  # Uzilgan connection'larni avtomatik aniqlash
    pool_recycle=1800,   # 30 daqiqada eski connection'larni yangilash
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


# Migratsiyalar: yangi ustunlar (mavjud baza uchun) — PostgreSQL sintaksisi
_MIGRATIONS = [
    "ALTER TABLE questions ADD COLUMN IF NOT EXISTS max_points INTEGER",
    # Har bir foydalanuvchi uchun faqat bitta "ochiq" (active/started/processing)
    # attempt bo'lishini kafolatlaydi — bir vaqtda ikkita moslama ochilsa ham
    # ikkinchi INSERT DB darajasida rad etiladi (race condition himoyasi).
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_test_attempts_one_open_per_user "
    "ON test_attempts (user_id) "
    "WHERE status IN ('active', 'started', 'processing')",
    # Attempt yuborilgan chat (UX — tugma/xabar yuborish uchun). Ishonchli
    # emas: faqat UX uchun, avtorizatsiya qaroriga ishlatilmaydi.
    "ALTER TABLE test_attempts ADD COLUMN IF NOT EXISTS chat_id BIGINT",
    # Har bir attempt-question juftligi uchun faqat bitta answer bo'lishini
    # kafolatlaydi — concurrent upload da duplicate answer bo'lishini oldini oladi.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_answers_one_per_attempt_question "
    "ON answers (attempt_id, question_id)",
]


_logger = logging.getLogger(__name__)

# Ishga tushishda bazaga ulanish urinishlari (soniya): PostgreSQL hali
# ishga tushmagan yoki ulanish bir martalik uzilgan bo'lsa ham bot yiqilmaydi.
_DB_CONNECT_DELAYS = (2, 4, 8, 16)


def _db_location() -> str:
    """Parolsiz manzil (log uchun): host:port/baza."""
    try:
        url = engine.url
        return f"{url.host}:{url.port or 5432}/{url.database}"
    except Exception:  # noqa: BLE001
        return "?"


async def _wait_for_database() -> None:
    for attempt in range(len(_DB_CONNECT_DELAYS) + 1):
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            if attempt == len(_DB_CONNECT_DELAYS):
                _logger.error(
                    "❌ PostgreSQL bazasiga ulanib bo'lmadi (%s): %s\n"
                    "   Tekshiring: 1) PostgreSQL ishlayaptimi (Windows: services.msc → "
                    "postgresql-x64-...); 2) .env dagi DATABASE_URL to'g'rimi "
                    "(host, port, parol, baza nomi); 3) baza yaratilganmi.",
                    _db_location(), type(exc).__name__,
                )
                raise
            delay = _DB_CONNECT_DELAYS[attempt]
            _logger.warning(
                "⚠️ Bazaga ulanib bo'lmadi (%s): %s — %d soniyadan keyin qayta urinish (%d/%d)",
                _db_location(), type(exc).__name__, delay, attempt + 1, len(_DB_CONNECT_DELAYS),
            )
            await engine.dispose()
            await asyncio.sleep(delay)


async def init_db() -> None:
    from app.database.models import (
        User,
        Question,
        TestAttempt,
        Answer,
    )

    await _wait_for_database()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        for statement in _MIGRATIONS:
            try:
                await connection.execute(text(statement))
            except Exception:
                # Ustun allaqachon mavjud — o'tkazib yuboriladi
                pass


async_session = SessionLocal
