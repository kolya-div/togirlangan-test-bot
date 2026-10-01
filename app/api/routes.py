import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from uuid import uuid4
from datetime import datetime

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.database import SessionLocal
from app.database.models import Answer, Question, TestAttempt, User
from app.database.repositories import get_test_settings, get_user_attempt_count_today
from app.services.report_service import MAX_TOTAL_POINTS
from app.services.report_worker import enqueue_report
from app.utils.helpers import utcnow
from app.utils.security import get_telegram_user_id, validate_telegram_webapp_data
from app.utils.validators import (
    validate_telegram_id,
    validate_string_input,
    sanitize_transcript,
    validate_audio_file_size
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# ──────────────────────────────────────────────
# STATUS CONSTANTS
# ──────────────────────────────────────────────
STATUS_ACTIVE = "active"
STATUS_LEGACY_STARTED = "started"
ACTIVE_STATUSES = {STATUS_ACTIVE, STATUS_LEGACY_STARTED}
STATUS_PROCESSING = "processing"
STATUS_FINISHED = "finished"

# Concurrent upload limit — 100 user bir vaqtda upload qilsa ham
# server RAM'i cheklangan bo'lishi uchun. Har bir upload ~64KB buffer
# ishlatadi (temp file ga yoziladi).
# Light: config'dan olinadi (default 100).
_UPLOAD_SEMAPHORE = asyncio.Semaphore(
    max(50, getattr(settings, "upload_semaphore", 100))
)
_UPLOAD_CHUNK_SIZE = 64 * 1024  # 64KB — RAM'da minimal iz qoldiradi


async def get_db():
    async with SessionLocal() as session:
        yield session


# Natijalar (ball, xatolar, transkript) foydalanuvchiga YUBORILMAYDI —
# ular faqat admin oladigan .docx hisobotda (kunlik va qo'lda eksport).
FINISH_MESSAGE = (
    "✅ Test yakunlandi!\n\n"
    "Javoblaringiz qabul qilindi. Rahmat!"
)


async def _send_telegram(telegram_id: int, text: str) -> None:
    """TelegramSender orqali xabar yuboradi — retry, 429, timeout bilan."""
    from app.services.telegram_sender import telegram_sender
    await telegram_sender.send_message(telegram_id, text)


# ──────────────────────────────────────────────
# QUESTIONS (read-only, himoya kerak emas)
# ──────────────────────────────────────────────
@router.get("/questions")
async def questions() -> list[dict]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Question)
            .where(Question.is_active.is_(True))
            .order_by(
                Question.section,
                Question.order_number,
            ),
        )
        items = result.scalars().all()

        data = [
            {
                "id": item.id,
                "section": item.section,
                "order_number": item.order_number,
                "text": item.text,
                "preparation_seconds": item.preparation_seconds,
                "answer_seconds": item.answer_seconds,
                "image_path": item.image_path,
                "pro_points": item.pro_points,
                "con_points": item.con_points,
                "max_points": item.max_points,
                "is_active": item.is_active,
            }
            for item in items
        ]

        return JSONResponse(
            content=data,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )


# ──────────────────────────────────────────────
# INIT — WEBAPP OCHILGANDA AVTORIZATSIYA VA STATUS
# ──────────────────────────────────────────────
@router.post("/init")
async def webapp_init(init_data: str = Form(...)) -> dict:
    """
    WebApp ochilishida chaqiriladi.

    Telegram initData imzosini validatsiya qilib, foydalanuvchini aniq
    va uning eng so'nggi attempt holatini qaytaradi. Agar test allaqachon
    topshirilgan (finished) yoki qayta ishlanayotgan (processing) bo'lsa —
    testga kirish rad etiladi.

    user_id FAQAT validatsiya qilingan initData dan olinadi — frontend
    tomonidan yuborilgan hech qanday user_id/query paramga ishonilmaydi.
    """
    # Validate init_data input
    try:
        init_data = validate_string_input(
            init_data,
            max_length=5000,
            field_name="init_data"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    user_id = get_telegram_user_id(init_data)
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Avtorizatsiya yaroqsiz yoki eskirgan. Botdan qayta oching.",
        )
    
    # Validate user_id
    try:
        user_id = validate_telegram_id(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()

        if not db_user:
            return {"user_id": user_id, "registered": False, "status": None}

        if not db_user.is_registered:
            return {"user_id": user_id, "registered": False, "status": None}

        if not db_user.is_admin:
            # Faqat user (admin bo'lmasa) attempt holatini tekshiramiz
            last = (
                await session.execute(
                    select(TestAttempt)
                    .where(TestAttempt.user_id == db_user.id)
                    .order_by(TestAttempt.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if last:
                return {
                    "user_id": user_id,
                    "registered": True,
                    "attempt_id": last.id,
                    "status": last.status,
                }

        return {"user_id": user_id, "registered": True, "status": None}


# ──────────────────────────────────────────────
# ATTEMPT — YARATISH / QAYTA KIRISH
# ──────────────────────────────────────────────
@router.post("/attempts")
async def create_attempt(
    init_data: str = Form(...),
    chat_id: int | None = Form(None),
) -> dict:
    """
    Yangi attempt yaratadi yoki mavjudni qaytaradi.

    user_id FAQAT validatsiya qilingan init_data dan olinadi (Telegram
    HMAC imzosi bilan tasdiqlangan). Frontend tomonidan yuborilgan
    hech qanday user_id/query paramga ishonilmaydi.

    chat_id — WebApp tugma yuborilgan chat (start_param orqali keladi).
    ⚠️ Ben ishonchsiz va imzolanmagan: FAQAT UX ("Test yakunlandi"
    xabari yuborish) uchun saqlanadi. Avtorizatsiya / user_id qaroriga
    ASLO ishlatilmaydi — user_id faqat init_data HMAC imzosidan olinadi.

    Qoidalar:
    - Agar foydalanuvchining tugallanmagan (active/processing) attempti bo'lsa — uni qaytaradi
    - Agar tugallangan (finished) attempti bo'lsa — 403 qaytaradi
    - Kunlik/VIP limit tekshiriladi
    - Yangi attempt faqat oldingi attempt yo'q bo'lganda yaratiladi
    """
    user_id = get_telegram_user_id(init_data)
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Avtorizatsiya yaroqsiz yoki eskirgan. Botdan qayta oching.",
        )

    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()

        if not db_user:
            db_user = User(telegram_id=user_id, is_registered=False)
            session.add(db_user)
            try:
                await session.commit()
                await session.refresh(db_user)
            except IntegrityError:
                # Parallel so'rov userni allaqachon yaratgan — qayta o'qiymiz
                await session.rollback()
                db_user = (
                    await session.execute(
                        select(User).where(User.telegram_id == user_id)
                    )
                ).scalar_one()

        # SECURITY: Ro'yxatdan o'tmagan foydalanuvchilar testga kirishlari
        # taqiqlanadi. Bot flow'ida har bir foydalanuvchi taklif havolasi
        # orqali ro'yxatdan o'tgan (start.py) — shuning uchun bu yerda
        # ro'yxatdan o'tmaganlarga ruxsat berish bot cheklovini chetlab
        # o'tish (bypass) bo'lar edi.
        if not db_user.is_admin and not db_user.is_registered:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Testni boshlash uchun avval bot orqali ro'yxatdan o'ting.",
                    "limit_reached": False,
                },
            )

        # Tekshir: mavjud attempt bormi?
        existing = (
            await session.execute(
                select(TestAttempt)
                .where(TestAttempt.user_id == db_user.id)
                .order_by(TestAttempt.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if existing:
            if existing.status == STATUS_FINISHED:
                # Test tugatilgan — qayta kirish har doim taqiqlanadi
                raise HTTPException(
                    status_code=403,
                    detail={
                        "message": "Siz allaqachon bu testni topshirgansiz. Qayta kirish mumkin emas.",
                        "attempt_id": existing.id,
                        "status": existing.status,
                        "limit_reached": True,
                    },
                )

            if existing.status in ACTIVE_STATUSES:
                # Test boshlangan — javob yozilganmi yoki yo'qmi, qayta kirish
                # HAR DOIM taqiqlanadi. Kuniga faqat bitta test topshiriladi,
                # "Testni boshlash" tugmasi faqat bir marta ishlatilishi kerak.
                raise HTTPException(
                    status_code=403,
                    detail={
                        "message": "Siz allaqachon bu testni boshlagansiz. Qayta kirish mumkin emas.",
                        "attempt_id": existing.id,
                        "status": existing.status,
                        "limit_reached": True,
                    },
                )

            # processing — natija kutishi uchun mavjudni qaytarish
            return {
                "id": existing.id,
                "user_id": existing.user_id,
                "status": existing.status,
                "existing": True,
                "answered_question_ids": [],
            }

        # Yangi attempt yaratish - limit tekshirish
        test_settings = await get_test_settings(session)
        daily_limit = 1  # Default
        current_mode = "daily"  # Default

        if test_settings:
            current_mode = test_settings.test_mode
            if current_mode == "vip":
                daily_limit = test_settings.vip_limit

        # Bugun qancha test topshirganini hisoblash
        today_attempts = await get_user_attempt_count_today(session, db_user.id)

        if today_attempts >= daily_limit:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Siz allaqachon bu testni topshirgansiz. Ertaga yana urinib ko'rishingiz mumkin.",
                    "limit_reached": True,
                },
            )

        # Yangi attempt yaratish
        # DB darajasidagi partial unique index (bitta ochiq attempt / user)
        # tufayli bir vaqtda ikkita parallel so'rov faqat bitta attempt
        # yarata oladi. Ikkinchi si Insert IntegrityError beradi — o'shanda
        # mavjud ochiq attemptni qaytaramiz (race condition himoyasi).
        attempt = TestAttempt(
            user_id=db_user.id,
            status=STATUS_ACTIVE,
            started_at=utcnow(),
            # Faqat UX uchun ishonchsiz qiymat (init-data imzosidan EMAS)
            chat_id=chat_id,
        )
        session.add(attempt)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = (
                await session.execute(
                    select(TestAttempt)
                    .where(TestAttempt.user_id == db_user.id)
                    .order_by(TestAttempt.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing:
                return {
                    "id": existing.id,
                    "user_id": existing.user_id,
                    "status": existing.status,
                    "existing": True,
                    "answered_question_ids": [],
                }
            # Bitta ham ochiq attempt topilmadi — rasmiy xato
            raise HTTPException(
                status_code=409,
                detail="Testni yaratishda ziddiyat yuz berdi. Qayta urinib ko'ring.",
            )
        await session.refresh(attempt)

        return {
            "id": attempt.id,
            "user_id": attempt.user_id,
            "status": attempt.status,
            "existing": False,
            "answered_question_ids": [],
        }


# ──────────────────────────────────────────────
# ANSWER — AUDIO YUKLASH
# ──────────────────────────────────────────────
@router.post("/attempts/{attempt_id}/answers/{question_id}")
async def upload_answer(
    attempt_id: int,
    question_id: int,
    audio: UploadFile = File(...),
    init_data: str = Form(...),
) -> dict:
    """
    Audio faylni yuklaydi (streaming — RAM kam ishlatadi).

    Security:
    - Authorization: Telegram initData HMAC imzosi
    - Ownership: attempt.user_id == verified_user_id
    - Question validation: question_id mavjudligi va faolligi
    - Idempotent: qayta upload → mavjud answer qaytariladi
    - Concurrent safety: DB unique constraint + asyncio.Semaphore(50)
    - Memory safety: chunked streaming → temp file → final (RAM'da ~64KB)
    """
    async with _UPLOAD_SEMAPHORE:
        # Validate init_data input
        try:
            init_data = validate_string_input(
                init_data,
                max_length=5000,
                field_name="init_data"
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        # Authorization tekshirish
        user_id = get_telegram_user_id(init_data)
        if user_id is None:
            raise HTTPException(
                status_code=401,
                detail="Avtorizatsiya yaroqsiz yoki eskirgan. Botdan qayta oching.",
            )
        
        # Validate user_id
        try:
            user_id = validate_telegram_id(user_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        if not audio.filename:
            raise HTTPException(
                status_code=400,
                detail="Audio fayl topilmadi",
            )

        # Validate filename for security
        try:
            validate_string_input(
                audio.filename,
                max_length=255,
                field_name="audio_filename"
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        extension = Path(audio.filename).suffix.lower()
        if extension not in {".webm", ".ogg", ".mp4", ".wav", ".mp3"}:
            raise HTTPException(
                status_code=400,
                detail="Audio formati qo'llab-quvvatlanmaydi",
            )

        # ── Streaming upload → temp file ─────────────────────────
        # `await audio.read()` o'rniga chunked streaming — faqat ~64KB
        # RAM ishlatiladi. 100 parallel upload = ~6MB RAM (2.5GB emas).
        max_size_mb = getattr(settings, "max_audio_size_mb", 50) or 50
        MAX_UPLOAD_SIZE = max_size_mb * 1024 * 1024
        upload_dir = Path(settings.upload_dir) / str(attempt_id)
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Temp file — final fayl bilan bir xil filesystem'da (os.rename uchun)
        temp_fd = None
        temp_path = None
        try:
            temp_fd, temp_path = tempfile.mkstemp(
                suffix=extension,
                prefix=f".upload_{attempt_id}_{question_id}_",
                dir=str(upload_dir),
            )
            total_size = 0
            with os.fdopen(temp_fd, "wb") as temp_file:
                temp_fd = None  # os.fdopen egalladi
                while True:
                    chunk = await audio.read(_UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > MAX_UPLOAD_SIZE:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Audio fayl juda katta (maksimum {max_size_mb}MB)",
                        )
                    temp_file.write(chunk)

            # Validate file size using validator
            try:
                validate_audio_file_size(total_size, max_size_mb)
            except ValueError as e:
                raise HTTPException(status_code=413, detail=str(e))

            if total_size < 1024:
                raise HTTPException(
                    status_code=400,
                    detail="Audio fayl juda kichik yoki bo'sh",
                )

            # ── DB validation + upload ────────────────────────────
            async with SessionLocal() as session:
                # Attempt validation
                attempt = (
                    await session.execute(
                        select(TestAttempt).where(TestAttempt.id == attempt_id)
                    )
                ).scalar_one_or_none()

                if not attempt:
                    raise HTTPException(status_code=404, detail="Test topilmadi")

                # Ownership tekshirish
                user = await session.get(User, attempt.user_id)
                if not user or user.telegram_id != user_id:
                    raise HTTPException(
                        status_code=403,
                        detail="Bu test sizga tegishli emas.",
                    )

                if attempt.status not in ACTIVE_STATUSES:
                    raise HTTPException(
                        status_code=403,
                        detail="Test yakunlangan yoki qayta ishlanmoqda. Yangi javob yuborish mumkin emas.",
                    )

                # Question validation
                question = await session.get(Question, question_id)
                if not question or not question.is_active:
                    raise HTTPException(
                        status_code=404,
                        detail="Savol topilmadi",
                    )

                # Idempotent: mavjud answer bo'lsa — qaytaramiz
                existing_answer = (
                    await session.execute(
                        select(Answer).where(
                            Answer.attempt_id == attempt_id,
                            Answer.question_id == question_id
                        )
                    )
                ).scalar_one_or_none()

                if existing_answer:
                    existing_filename = Path(existing_answer.audio_path).name if existing_answer.audio_path else None
                    return {
                        "success": True,
                        "filename": existing_filename,
                        "existing": True,
                    }

                # DB record yaratish
                filename = f"{uuid4().hex}{extension}"
                file_path = upload_dir / filename
                answer = Answer(
                    attempt_id=attempt_id,
                    question_id=question_id,
                    audio_path=str(file_path),
                )
                session.add(answer)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    existing_answer = (
                        await session.execute(
                            select(Answer).where(
                                Answer.attempt_id == attempt_id,
                                Answer.question_id == question_id
                            )
                        )
                    ).scalar_one_or_none()
                    if existing_answer:
                        existing_filename = Path(existing_answer.audio_path).name if existing_answer.audio_path else None
                        return {
                            "success": True,
                            "filename": existing_filename,
                            "existing": True,
                        }
                    raise HTTPException(
                        status_code=409,
                        detail="Javob yaratishda ziddiyat yuz berdi. Qayta urinib ko'ring.",
                    )

            # Temp file → final location (os.rename — tez va atomic)
            os.replace(temp_path, file_path)
            temp_path = None  # muvaffaqiyatli — tozalamaysiz

            return {
                "success": True,
                "filename": filename,
                "existing": False,
            }

        finally:
            # Temp file tozalash (xato yoki muvaffaqiyat)
            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except OSError:
                    pass
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass


# ──────────────────────────────────────────────
# FINISH — TESTNI YAKUNLASH
# ──────────────────────────────────────────────
@router.post("/attempts/{attempt_id}/finish")
async def finish_attempt(
    attempt_id: int,
    init_data: str = Form(...),
) -> dict:
    """
    Testni yakunlaydi.

    user_id FAQAT validatsiya qilingan init_data dan olinadi (Telegram
    HMAC imzosi bilan tasdiqlangan). Faqat o'z attemptini yakunlash mumkin
    (ownership tekshiriladi).

    Idempotent: allaqachon finished/processing bo'lsa — xatosiz javob qaytaradi.

    Race condition himoyasi: SELECT ... FOR UPDATE ikkita parallel finish
    so'rovini ketma-ket sequence qiladi — faqat birinchisi active→processing
    o'tishi mumkin.

    Duplicate report himoyasi: enqueue_report _pending_attempts set orqali
    bir xil attempt_id ni navbatga qayta qo'shmaydi.
    """
    # Authorization tekshirish
    user_id = get_telegram_user_id(init_data)
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Avtorizatsiya yaroqsiz yoki eskirgan. Botdan qayta oching.",
        )

    async with SessionLocal() as session:
        # Attempt ni row lock bilan olish — parallel finish'larni serialize qiladi
        result = await session.execute(
            select(TestAttempt)
            .where(TestAttempt.id == attempt_id)
            .with_for_update()
        )
        attempt = result.scalar_one_or_none()

        if not attempt:
            raise HTTPException(status_code=404, detail="Test topilmadi")

        # Ownership tekshirish: faqat o'z attemptini yakunlash mumkin
        user = await session.get(User, attempt.user_id)
        if not user or user.telegram_id != user_id:
            raise HTTPException(
                status_code=403,
                detail="Bu test sizga tegishli emas.",
            )

        # ── Idempotent responses ──────────────────────────────
        if attempt.status == STATUS_FINISHED:
            raise HTTPException(
                status_code=409,
                detail="Bu test allaqachon yakunlangan.",
            )

        if attempt.status == STATUS_PROCESSING:
            raise HTTPException(
                status_code=409,
                detail="Test natijalari hozir qayta ishlanmoqda.",
            )

        if attempt.status not in ACTIVE_STATUSES:
            raise HTTPException(
                status_code=403,
                detail=f"Test holati: {attempt.status}. Yakunlab bo'lmaydi.",
            )

        # ── Status transition: active → processing ─────────────
        attempt.status = STATUS_PROCESSING
        attempt.finished_at = utcnow()
        await session.commit()

        # Answers sonini session yopilmasdan oldin olish
        answers_count = (
            await session.execute(
                select(func.count()).select_from(Answer).where(Answer.attempt_id == attempt_id)
            )
        ).scalar() or 0

        telegram_user_id = user.telegram_id if user else None

    # ── Session yopildi — DB connection release ──────────────────

    # Telegram xabar — DB connection ochiq emas
    if telegram_user_id:
        try:
            await _send_telegram(
                telegram_user_id,
                FINISH_MESSAGE,
            )
        except Exception as e:
            logger.warning("Foydalanuvchiga xabar yuborib bo'lmadi (tg=%s): %s", telegram_user_id, e)

    # Navbatga qo'shish — DB connection ochiq emas
    if not await enqueue_report(attempt_id, total_answers=answers_count):
        # Periodic recovery (app/main.py) keyinroq qayta navbatga qo'shadi.
        logger.warning("Attempt #%s navbatga qo'shilmadi — recovery kutiladi", attempt_id)

    return {
        "processing": True,
        "total_answers": answers_count,
        "max_score": 75,
    }


# ──────────────────────────────────────────────
# NOTIFY — WEBAPP YOPILGANDA XABAR YUBORISH
# ──────────────────────────────────────────────
@router.post("/attempts/{attempt_id}/notify-closed")
async def notify_attempt_closed(
    attempt_id: int,
    init_data: str = Form(...),
) -> dict:
    """
    WebApp dagi 'Yopish' tugmasi bosilganda foydalanuvchiga
    Telegram orqali test yakunlangani va javoblar qabul qilinganini bildiradi.

    user_id FAQAT validatsiya qilingan init_data dan olinadi (Telegram
    HMAC imzosi bilan tasdiqlangan). Faqat o'z attemptiga notification
    yuborish mumkin (ownership tekshiriladi).
    """
    # Authorization tekshirish
    user_id = get_telegram_user_id(init_data)
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Avtorizatsiya yaroqsiz yoki eskirgan. Botdan qayta oching.",
        )

    async with SessionLocal() as session:
        attempt = (
            await session.execute(
                select(TestAttempt).where(TestAttempt.id == attempt_id)
            )
        ).scalar_one_or_none()

        if not attempt:
            raise HTTPException(status_code=404, detail="Test topilmadi")

        # Ownership tekshirish: faqat o'z attemptiga notification yuborish mumkin
        user = await session.get(User, attempt.user_id)
        if not user or user.telegram_id != user_id:
            raise HTTPException(
                status_code=403,
                detail="Bu test sizga tegishli emas.",
            )

    if user:
        try:
            await _send_telegram(
                user.telegram_id,
                FINISH_MESSAGE,
            )
        except Exception as e:
            logger.warning(f"Yopish xabari yuborilmadi (tg={user.telegram_id}): {e}")

    return {"success": True}


# ──────────────────────────────────────────────
# RESULTS — NATIJALARNI KO'RISH
# ──────────────────────────────────────────────
@router.get("/attempts/{attempt_id}/results")
async def get_attempt_results(
    attempt_id: int,
    init_data: str = Query(..., description="Telegram WebApp initData"),
) -> dict:
    """
    Test natijalarini qaytaradi.

    Ownership: Telegram imzosi bilan tasdiqlanib, faqat o'zining
    attemptini ko'ra oladi. init_data MANDATORY - xavfsizlik uchun
    user_id query param qabul qilinmaydi.
    """
    # Authorization tekshirish
    user_id = get_telegram_user_id(init_data)
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Avtorizatsiya yaroqsiz yoki eskirgan. Botdan qayta oching.",
        )

    async with SessionLocal() as session:
        attempt = (
            await session.execute(
                select(TestAttempt).where(TestAttempt.id == attempt_id)
            )
        ).scalar_one_or_none()

        if not attempt:
            raise HTTPException(status_code=404, detail="Test topilmadi")

        # OWNERSHIP TEKSHIRISH — init_data validatsiyasi orqali
        user = (
            await session.execute(
                select(User).where(User.id == attempt.user_id)
            )
        ).scalar_one_or_none()
        if not user or user.telegram_id != user_id:
            raise HTTPException(
                status_code=403,
                detail="Bu test sizga tegishli emas.",
            )

        # Foydalanuvchi natijani ko'rmaydi — faqat test holati. Batafsil
        # natija (ball, xatolar) faqat adminga (.docx hisobotda).
        if user_id not in settings.admin_id_list:
            return {"attempt_id": attempt_id, "status": attempt.status}

        answers = (
            await session.execute(
                select(Answer).where(Answer.attempt_id == attempt_id)
            )
        ).scalars().all()

        results = []
        for answer in answers:
            question = await session.get(Question, answer.question_id)

            feedback_data = {}
            if answer.feedback:
                try:
                    feedback_data = json.loads(answer.feedback)
                except json.JSONDecodeError:
                    pass

            results.append({
                "answer_id": answer.id,
                "question_id": answer.question_id,
                "question_text": question.text if question else "",
                "question_section": question.section if question else "",
                "question_order": question.order_number if question else 0,
                "max_points": question.max_points if question else None,
                "transcript": sanitize_transcript(feedback_data.get("transcript", answer.transcript or "")),
                "corrected_text": feedback_data.get("corrected_text", ""),
                "is_grammatically_correct": feedback_data.get("is_grammatically_correct", True),
                "mistakes": feedback_data.get("mistakes", []),
                "scores": feedback_data.get("scores", {}),
                "score_reasons": feedback_data.get("score_reasons", []),
                "strengths": feedback_data.get("strengths", []),
                "feedback_uz": feedback_data.get("feedback_uz", ""),
                "feedback_tr": feedback_data.get("feedback_tr", ""),
                "score": answer.score,
            })

        results.sort(key=lambda r: (r["question_section"], r["question_order"]))

        return {
            "attempt_id": attempt_id,
            "total_score": attempt.score,
            "max_score": MAX_TOTAL_POINTS,
            "level": attempt.level,
            "status": attempt.status,
            "results": results,
        }


# ──────────────────────────────────────────────
# REPORT STATUS — Foydalanuvchi report holatini so'rashi mumkin
# ──────────────────────────────────────────────
@router.get("/attempts/{attempt_id}/status")
async def get_attempt_status(
    attempt_id: int,
    init_data: str = Query(...),
):
    """Report processing holatini qaytaradi. Bot orqali polling uchun."""
    from app.services.job_tracker import job_tracker

    user_id = get_telegram_user_id(init_data)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")

    async with SessionLocal() as session:
        attempt = await session.get(TestAttempt, attempt_id)
        if not attempt:
            raise HTTPException(status_code=404, detail="Attempt topilmadi")

        user = await session.get(User, attempt.user_id)
        if not user or user.telegram_id != user_id:
            raise HTTPException(status_code=403, detail="Ruxsat yo'q")

        # Agar attempt allaqachon finished bo'lsa — to'g'ridan-to'g'ri qaytar
        if attempt.status == "finished":
            data = {
                "attempt_id": attempt_id,
                "status": "completed",
                "progress_pct": 100,
            }
            # Ball/daraja foydalanuvchiga ko'rsatilmaydi — faqat adminga
            if user_id in settings.admin_id_list:
                data["score"] = attempt.score
                data["level"] = attempt.level
            return data

        # Job tracker'dan real-vaqt status olish
        job = await job_tracker.get_job(attempt_id)
        if job:
            return {
                "attempt_id": attempt_id,
                "status": job.status.value,
                "progress_pct": job.progress_pct,
                "current_step": job.current_step,
                "elapsed_seconds": job.elapsed,
                "queue_wait_seconds": job.queue_wait_time,
                "error": job.error if job.status == "failed" else None,
            }

        return {
            "attempt_id": attempt_id,
            "status": attempt.status,
            "progress_pct": 0,
        }


# ──────────────────────────────────────────────
# AI PROVIDER HEALTH — Admin monitoring uchun
# ──────────────────────────────────────────────
@router.get("/admin/ai-health")
async def get_ai_health(init_data: str = Query(...)):
    """AI providerlar holatini qaytaradi. Admin monitoring uchun."""
    user_id = get_telegram_user_id(init_data)
    if user_id not in settings.admin_id_list:
        raise HTTPException(status_code=403, detail="Admin emas")

    from app.services.ai_resource_manager import ai_manager
    from app.services.job_tracker import job_tracker

    providers = ai_manager.get_all_health()
    queue_stats = await job_tracker.get_stats()

    return {
        "providers": providers,
        "queue": queue_stats,
    }


# ──────────────────────────────────────────────
# TELEGRAM HEALTH — Yuborish xizmati monitoring
# ──────────────────────────────────────────────
@router.get("/admin/telegram-health")
async def get_telegram_health(init_data: str = Query(...)):
    """Telegram yuborish xizmati holatini qaytaradi. Admin monitoring uchun."""
    user_id = get_telegram_user_id(init_data)
    if user_id not in settings.admin_id_list:
        raise HTTPException(status_code=403, detail="Admin emas")

    from app.services.telegram_sender import telegram_sender

    return telegram_sender.metrics.to_dict()


# ──────────────────────────────────────────────
# AUTHENTICATED AUDIO SERVING — User audio fayllari
# ──────────────────────────────────────────────
from fastapi.responses import FileResponse

@router.get("/audios/{filename:path}")
async def serve_audio(filename: str, init_data: str = Query(...)):
    """Audio faylni autentifikatsiya bilan xizmat qiladi.

    SECURITY: StaticFiles olib tashlangan — user audio fayllari
    endi faqat Telegram imzo tekshirilgandan keyin ochiladi.
    Path traversal himoyasi: .., //, absolute path bloklanadi.
    """
    user_id = get_telegram_user_id(init_data)

    # SECURITY: Path traversal himoyasi
    if ".." in filename or "//" in filename:
        raise HTTPException(status_code=403, detail="Noto'g'ri audio yo'li")

    audio_path = Path(settings.upload_dir) / filename
    audio_path = audio_path.resolve()  # Normalize qilish

    # SECURITY: Fayl upload_dir ichida ekanligini tekshirish
    upload_dir_resolved = Path(settings.upload_dir).resolve()
    if not str(audio_path).startswith(str(upload_dir_resolved)):
        raise HTTPException(status_code=403, detail="Noto'g'ri audio yo'li")

    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio topilmadi")

    # Fayl nomidan attempt ID ni ajratib olish
    # Format: {attempt_id}/{uuid}.webm
    parts = filename.split("/", 1)
    if len(parts) == 1:
        raise HTTPException(status_code=403, detail="Noto'g'ri audio yo'li")

    attempt_id_str = parts[0]
    try:
        attempt_id = int(attempt_id_str)
    except ValueError:
        raise HTTPException(status_code=403, detail="Noto'g'ri attempt ID")

    async with SessionLocal() as session:
        attempt = await session.get(TestAttempt, attempt_id)
        if not attempt:
            raise HTTPException(status_code=404, detail="Attempt topilmadi")
        user = await session.get(User, attempt.user_id)
        if not user or user.telegram_id != user_id:
            raise HTTPException(status_code=403, detail="Bu audio sizga tegishli emas")

    return FileResponse(str(audio_path))
