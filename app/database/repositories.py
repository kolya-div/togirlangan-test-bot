import json

from sqlalchemy import Date, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Answer, Question, TestAttempt, User, TestSettings
from app.utils.helpers import utcnow
from app.utils.cache import cached, questions_cache, test_settings_cache


# ==================== USER ====================

async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    full_name: str | None,
    admin_ids: list[int],
) -> User:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id),
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
            is_admin=telegram_id in admin_ids,
        )
        session.add(user)
        try:
            await session.commit()
        except IntegrityError:
            # Poyga: bir xil foydalanuvchining bir nechta /start'i bir
            # vaqtda qayta ishlanganda (masalan bot qayta ishga tushgach
            # to'planib qolgan xabarlar) boshqa so'rov userni allaqachon
            # yaratgan — uni qayta o'qiymiz.
            await session.rollback()
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id),
            )
            user = result.scalar_one()
        else:
            await session.refresh(user)
            return user

    # ADMIN_IDS o'zgartirilsa — mavjud foydalanuvchining admin holati ham
    # yangilanadi (oldin faqat birinchi /start da yozilardi: eski admin
    # admin bo'lib qolar, yangisi admin bo'lmasdi)
    should_be_admin = telegram_id in admin_ids
    if user.is_admin != should_be_admin:
        user.is_admin = should_be_admin
        await session.commit()
        await session.refresh(user)

    return user


async def sync_admin_flags(session: AsyncSession, admin_ids: list[int]) -> int:
    """Bazadagi is_admin ni ADMIN_IDS ga moslaydi (ishga tushganda).
    Qaytaradi: o'zgargan foydalanuvchilar soni."""
    ids = list(admin_ids) or [-1]
    granted = await session.execute(
        update(User)
        .where(User.telegram_id.in_(ids), User.is_admin.is_(False))
        .values(is_admin=True)
    )
    revoked = await session.execute(
        update(User)
        .where(User.telegram_id.not_in(ids), User.is_admin.is_(True))
        .values(is_admin=False)
    )
    await session.commit()
    return (granted.rowcount or 0) + (revoked.rowcount or 0)


async def get_user_by_telegram_id(
    session: AsyncSession,
    telegram_id: int,
) -> User | None:
    """Telegram ID bo'yicha foydalanuvchini olish."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id),
    )
    return result.scalar_one_or_none()


async def count_users(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count(User.id)).where(
            User.is_registered.is_(True),
        ),
    )
    return int(result.scalar_one())


async def get_registered_users(session: AsyncSession) -> list[User]:
    """Ro'yxatdan o'tgan barcha foydalanuvchilarni olish."""
    result = await session.execute(
        select(User).where(
            User.is_registered.is_(True),
            User.is_admin.is_(False),
        )
    )
    return list(result.scalars().all())


# ==================== QUESTIONS ====================

@cached(questions_cache, ttl=600)  # Cache for 10 minutes
async def get_all_questions(session: AsyncSession) -> list[Question]:
    """Barcha savollarni bo'lim va tartib raqami bo'yicha olish."""
    result = await session.execute(
        select(Question).order_by(
            Question.section,
            Question.order_number,
        ),
    )
    return list(result.scalars().all())


@cached(questions_cache, ttl=600)  # Cache for 10 minutes
async def get_questions_by_section(session: AsyncSession, section: str) -> list[Question]:
    """Berilgan bo'limdagi savollarni olish."""
    result = await session.execute(
        select(Question)
        .where(Question.section == section)
        .order_by(Question.order_number)
    )
    return list(result.scalars().all())


async def add_question(
    session: AsyncSession,
    section: str,
    order_number: int,
    text: str,
    preparation_seconds: int,
    answer_seconds: int,
    sub_questions: list[str] | None = None,
    image_path: str | None = None,
    pro_points: str | None = None,
    con_points: str | None = None,
    max_points: int | None = None,
) -> Question:
    """Yangi savol qo'shish."""
    # Invalidate cache when questions are modified
    await questions_cache.clear()
    
    question = Question(
        section=section,
        order_number=order_number,
        text=text,
        preparation_seconds=preparation_seconds,
        answer_seconds=answer_seconds,
        sub_questions=json.dumps(sub_questions, ensure_ascii=False) if sub_questions else None,
        image_path=image_path,
        pro_points=pro_points,
        con_points=con_points,
        max_points=max_points,
    )
    session.add(question)
    await session.commit()
    await session.refresh(question)
    return question


async def delete_all_questions(session: AsyncSession) -> None:
    """Barcha savollarni o'chirish."""
    # Invalidate cache when questions are deleted
    await questions_cache.clear()
    
    await session.execute(delete(Question))
    await session.commit()


async def get_questions_count(session: AsyncSession) -> int:
    """Savollar sonini olish."""
    result = await session.execute(select(func.count(Question.id)))
    return int(result.scalar_one())


# ==================== TEST & ANSWERS ====================

async def delete_all_data(session: AsyncSession) -> None:
    """Barcha ma'lumotlarni tozalash (adminlarni tashlab)."""
    await session.execute(delete(Answer))
    await session.execute(delete(TestAttempt))
    await session.execute(delete(Question))
    await session.execute(
        delete(User).where(User.is_admin.is_(False)),
    )
    await session.commit()


# ==================== TEST SETTINGS ====================

@cached(test_settings_cache, ttl=300)  # Cache for 5 minutes
async def get_test_settings(session: AsyncSession) -> TestSettings | None:
    """Hozirgi test sozlamalarini olish."""
    result = await session.execute(
        select(TestSettings).order_by(TestSettings.id.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def create_or_update_test_settings(
    session: AsyncSession,
    test_mode: str,
    vip_limit: int = 1,
) -> TestSettings:
    """Test sozlamalarini yaratish yoki yangilash."""
    # Invalidate cache when settings are updated
    await test_settings_cache.clear()
    
    today = utcnow().date()
    result = await session.execute(
        select(TestSettings).where(
            TestSettings.date.cast(Date) == today
        ).order_by(TestSettings.id.desc()).limit(1)
    )
    settings_row = result.scalar_one_or_none()

    if settings_row:
        settings_row.test_mode = test_mode
        settings_row.vip_limit = vip_limit
        settings_row.updated_at = utcnow()
    else:
        settings_row = TestSettings(
            test_mode=test_mode,
            vip_limit=vip_limit,
            date=utcnow(),
        )
        session.add(settings_row)

    await session.commit()
    await session.refresh(settings_row)
    return settings_row


async def _upsert_test_active(session: AsyncSession, is_active: bool) -> None:
    """
    FIX #1: test holati DB da saqlanadi.
    Mavjud TestSettings yozuvini yangilaydi; yo'q bo'lsa yaratadi.
    """
    result = await session.execute(
        select(TestSettings).order_by(TestSettings.id.desc()).limit(1)
    )
    settings_row = result.scalar_one_or_none()

    if settings_row:
        settings_row.is_active = is_active
        settings_row.updated_at = utcnow()
    else:
        settings_row = TestSettings(is_active=is_active, date=utcnow())
        session.add(settings_row)

    await session.commit()


async def _upsert_invite_token(session: AsyncSession, token: str | None) -> None:
    """
    FIX #2: invite token DB da saqlanadi — restart safe.
    """
    result = await session.execute(
        select(TestSettings).order_by(TestSettings.id.desc()).limit(1)
    )
    settings_row = result.scalar_one_or_none()

    if settings_row:
        settings_row.invite_token = token
        settings_row.updated_at = utcnow()
    else:
        settings_row = TestSettings(invite_token=token, date=utcnow())
        session.add(settings_row)

    await session.commit()


async def get_user_attempt_count_today(
    session: AsyncSession,
    user_id: int,
) -> int:
    """Foydalanuvchining bugun qancha test topshirganini hisoblash."""
    today = utcnow().date()
    result = await session.execute(
        select(func.count(TestAttempt.id)).where(
            TestAttempt.user_id == user_id,
            TestAttempt.started_at.cast(Date) == today,
        )
    )
    return int(result.scalar_one())


async def get_user_last_attempt(
    session: AsyncSession,
    user_id: int,
) -> TestAttempt | None:
    """Foydalanuvchining eng so'nggi attemptini olish."""
    result = await session.execute(
        select(TestAttempt)
        .where(TestAttempt.user_id == user_id)
        .order_by(TestAttempt.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_attempt_answer_count(
    session: AsyncSession,
    attempt_id: int,
) -> int:
    """Berilgan attemptdagi javoblar soni."""
    result = await session.execute(
        select(func.count(Answer.id)).where(Answer.attempt_id == attempt_id)
    )
    return int(result.scalar_one())


# ==================== RESULTS / ADMIN ====================

async def get_recent_attempts(
    session: AsyncSession,
    limit: int = 10,
    offset: int = 0,
) -> list[tuple[TestAttempt, User]]:
    """So'nggi test attempts: (attempt, user) juftliklari."""
    result = await session.execute(
        select(TestAttempt, User)
        .join(User, TestAttempt.user_id == User.id)
        .order_by(TestAttempt.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.all())


async def get_attempts_count(session: AsyncSession) -> int:
    """Barcha attempts soni."""
    result = await session.execute(select(func.count(TestAttempt.id)))
    return int(result.scalar_one())


async def search_users(session: AsyncSession, query: str) -> list[User]:
    """Foydalanuvchini telegram_id, username yoki ism bo'yicha qidirish."""
    q = query.strip().lstrip("@")
    if q.isdigit():
        result = await session.execute(
            select(User).where(User.telegram_id == int(q)),
        )
        return list(result.scalars().all())

    like = f"%{q}%"
    result = await session.execute(
        select(User).where(
            User.username.ilike(like) | User.full_name.ilike(like),
        )
    )
    return list(result.scalars().all())


async def get_user_attempts(
    session: AsyncSession,
    user_id: int,
) -> list[TestAttempt]:
    """Foydalanuvchining barcha attempts (eng yangisi birinchi)."""
    result = await session.execute(
        select(TestAttempt)
        .where(TestAttempt.user_id == user_id)
        .order_by(TestAttempt.id.desc())
    )
    return list(result.scalars().all())