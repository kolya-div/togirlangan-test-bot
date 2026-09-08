from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base
from app.utils.helpers import utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
    )
    username: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
    )

    attempts: Mapped[list["TestAttempt"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    section: Mapped[str] = mapped_column(String(50), index=True)
    order_number: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text)

    # Tayyorgarlik va javob vaqti (soniyalarda)
    preparation_seconds: Mapped[int] = mapped_column(Integer, default=10)
    answer_seconds: Mapped[int] = mapped_column(Integer, default=30)

    # Rasm va qo'shimcha ma'lumotlar
    image_path: Mapped[str | None] = mapped_column(String(500))
    sub_questions: Mapped[str | None] = mapped_column(Text)  # JSON string
    pro_points: Mapped[str | None] = mapped_column(Text)  # Bölüm 3 uchun Lehine
    con_points: Mapped[str | None] = mapped_column(Text)  # Bölüm 3 uchun Aleyhine

    # Savol uchun maksimal ball (docx da "Ball: N" bilan beriladi)
    max_points: Mapped[int | None] = mapped_column(Integer)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
    )


class TestAttempt(Base):
    __tablename__ = "test_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="active",
    )
    level: Mapped[str | None] = mapped_column(String(30))
    score: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    # WebApp tugma yuborilgan chat (UX uchun). Imzolanmagan va ishonchsiz —
    # FAQAT "Test yakunlandi" xabarini yuborish uchun. Avtorizatsiya/
    # user_id uchun ASLO ishlatilmaydi (u faqat init_data HMAC imzosidan).
    chat_id: Mapped[int | None] = mapped_column(BigInteger)

    user: Mapped["User"] = relationship(back_populates="attempts")
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="attempt",
        cascade="all, delete-orphan",
    )


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("test_attempts.id", ondelete="CASCADE"),
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"),
    )

    audio_path: Mapped[str | None] = mapped_column(String(500))
    transcript: Mapped[str | None] = mapped_column(Text)
    feedback: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int | None] = mapped_column(Integer)

    attempt: Mapped["TestAttempt"] = relationship(
        back_populates="answers",
    )


class TestSettings(Base):
    __tablename__ = "test_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    test_mode: Mapped[str] = mapped_column(
        String(20),
        default="daily",  # "daily" or "vip"
    )
    vip_limit: Mapped[int] = mapped_column(
        Integer,
        default=1,  # VIP modeda kunlik limit
    )
    date: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
    )