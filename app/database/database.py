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


async def init_db() -> None:
    from app.database.models import (
        User,
        Question,
        TestAttempt,
        Answer,
    )

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        for statement in _MIGRATIONS:
            try:
                await connection.execute(text(statement))
            except Exception:
                # Ustun allaqachon mavjud — o'tkazib yuboriladi
                pass


async_session = SessionLocal
