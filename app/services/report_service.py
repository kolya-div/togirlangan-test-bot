"""
Test yakunlangach natijalarni qayta ishlash va Telegram hisobot yuborish.

1. Har bir javob audio fayli matnga aylantiriladi (Whisper).
2. AI javobni baholaydi: ball, xatolar, fikr.
3. Telegram chatiga yuboriladi: transcript + xatolar + ball + audio yozuvlar
   va oxirida umumiy ball bilan daraja.
"""

import asyncio
import html
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from app.config import settings
from app.database.database import SessionLocal
from app.database.models import Answer, Question, TestAttempt, User
from app.services.evaluation_service import evaluate_answer
from app.services.transcription_service import transcribe_audio

logger = logging.getLogger(__name__)

MAX_MESSAGE_LEN = 4000

# Umumiy maksimal ball — qat'iy 75 (docx ballari faqat vazn sifatida)
MAX_TOTAL_POINTS = 75

# 100 user uchun: Gemini paid 300 RPM = ko'plab concurrent call.
# Workerlar o'zi cheklaydi (REPORT_WORKERS), lekin semaphore ham
# ortiqcha parallel AI call'larni oldini oladi.
from app.config import settings as _rsettings
_REPORT_SEMAPHORE = asyncio.Semaphore(
    max(10, getattr(_rsettings, "report_workers", 8)) * 2
)


async def process_attempt_and_report(attempt_id: int) -> None:
    """Test natijalarini qayta ishlaydi va Telegram hisobotini yuboradi."""
    async with _REPORT_SEMAPHORE:
        await _process_attempt_and_report_inner(attempt_id)


async def _process_attempt_and_report_inner(attempt_id: int) -> None:
    from app.services.job_tracker import job_tracker

    # ─── 1-QADAM: Ma'lumotlarni olish — QISQA session ───────────
    async with SessionLocal() as session:
        attempt = (
            await session.execute(
                select(TestAttempt).where(TestAttempt.id == attempt_id)
            )
        ).scalar_one_or_none()

        if not attempt:
            logger.error("Hisobot: attempt #%d topilmadi", attempt_id)
            return

        user = await session.get(User, attempt.user_id)

        answers = (
            await session.execute(
                select(Answer).where(Answer.attempt_id == attempt_id)
            )
        ).scalars().all()

        questions = {}
        for answer in answers:
            question = await session.get(Question, answer.question_id)
            if question:
                questions[question.id] = question

        answers_data = []
        for a in answers:
            answers_data.append({
                "id": a.id,
                "question_id": a.question_id,
                "audio_path": a.audio_path,
                "transcript": a.transcript,
                "score": a.score,
                "feedback": a.feedback,
            })
        attempt_user_id = attempt.user_id

    # ─── 2-QADAM: AI transkripsiya + baholash — SESSION YO'Q ─────
    ordered = sorted(
        answers_data,
        key=lambda a: (
            getattr(questions.get(a["question_id"]), "section", ""),
            getattr(questions.get(a["question_id"]), "order_number", 0),
        ),
    )

    total = len(ordered)
    for idx, item in enumerate(ordered):
        question = questions.get(item["question_id"])

        # Progress tracking
        await job_tracker.update_progress(
            attempt_id,
            step=f"transcribing:{idx + 1}/{total}",
            processed=idx,
            total=total,
        )

        if not item["transcript"] and item["audio_path"]:
            try:
                item["transcript"] = await transcribe_audio(item["audio_path"])
            except Exception as e:
                logger.warning("Javob #%d transkripsiyasi xato: %s", item["id"], e)
                # Transkripsiya xatosi — javobni qoldiramiz, baholashda bo'sh transcript bilan ishlaymiz

        # Evaluation
        if item["transcript"] and item["score"] is None and question:
            await job_tracker.update_progress(
                attempt_id,
                step=f"evaluating:{idx + 1}/{total}",
                processed=idx,
                total=total,
            )
            try:
                evaluation = await evaluate_answer(question.text, item["transcript"])
                item["score"] = evaluation.get("score", 0)
                item["feedback"] = json.dumps(
                    {
                        "transcript": item["transcript"],
                        "corrected_text": evaluation.get("corrected_text", item["transcript"]),
                        "is_grammatically_correct": evaluation.get("is_grammatically_correct", True),
                        "mistakes": evaluation.get("mistakes", []),
                        "scores": evaluation.get("scores", {}),
                        "score_reasons": evaluation.get("score_reasons", []),
                        "strengths": evaluation.get("strengths", []),
                        "feedback_uz": evaluation.get("feedback_uz", ""),
                        "feedback_tr": evaluation.get("feedback_tr", ""),
                    },
                    ensure_ascii=False,
                )
            except Exception as e:
                logger.warning("Javob #%d baholanmadi: %s", item["id"], e)
                # Baholash xatosi — ball 0, lekin javob saqlanadi

    # ─── 3-QADAM: Natijalarni saqlash — QISQA session ───────────
    async with SessionLocal() as session:
        for item in ordered:
            answer = await session.get(Answer, item["id"])
            if answer:
                answer.transcript = item["transcript"]
                answer.score = item["score"]
                answer.feedback = item["feedback"]

        await session.commit()

        scored = [item["score"] for item in ordered if item["score"] is not None]

        points_map: dict[int, dict] = {}
        raw_earned = 0
        raw_possible = 0
        for item in ordered:
            q = questions.get(item["question_id"])
            pts = int(q.max_points) if (q and q.max_points) else None
            if pts:
                earned = round((item["score"] or 0) * pts / 100) if item["score"] is not None else 0
                raw_earned += earned
                raw_possible += pts
            else:
                earned = None
            points_map[item["id"]] = {"pts": pts, "earned": earned}

        if raw_possible > 0:
            total_earned = round(raw_earned * MAX_TOTAL_POINTS / raw_possible)
        else:
            avg = round(sum(scored) / len(scored)) if scored else 0
            total_earned = round(avg * MAX_TOTAL_POINTS / 100)
        total_possible = MAX_TOTAL_POINTS

        attempt = await session.get(TestAttempt, attempt_id)
        if attempt:
            attempt.score = total_earned
            attempt.level = _score_to_level(total_earned)
            attempt.status = "finished"
            await session.commit()

    # ─── 4-QADAM: Telegram hisobot — SESSION YO'Q ───────────────
    if user is None:
        logger.warning("Hisobot: attempt #%d uchun user topilmadi", attempt_id)
        return

    try:
        await _send_report(
            user.telegram_id,
            ordered,
            questions,
            total_earned,
            total_possible,
            points_map,
            attempt_id=attempt_id,
        )
    except Exception as e:
        logger.error("Hisobot yuborishda xato (tg=%s): %s", user.telegram_id, e)


def _score_to_level(score: int) -> str:
    """75 ballik shkala: B1 >= 38, B2 >= 51, C1 >= 65.
    Past bo'lsa 'Below B1' qaytariladi."""
    if score >= 65:
        return "C1"
    if score >= 51:
        return "B2"
    if score >= 38:
        return "B1"
    return "Below B1"


def _annotate(transcript: str, mistakes: list) -> str:
    """Xato so'zlarni belgilangan transcript."""
    text = html.escape(transcript.strip())
    for m in mistakes:
        original = m.get("original") or ""
        correct = m.get("correct") or ""
        if not original or original.lower() == correct.lower():
            continue
        pattern = re.compile(re.escape(html.escape(original)), re.IGNORECASE)
        if pattern.search(text):
            text = pattern.sub(
                "<s>" + html.escape(original) + "</s>➡️<b>" + html.escape(correct) + "</b>",
                text,
                count=1,
            )
    return text


def _answer_text(idx: int, total: int, answer: Answer, question, pts_info: dict | None = None) -> str:
    parts = ["❓ <b>Savol " + str(idx) + "/" + str(total)]
    if question:
        parts[0] += " (" + html.escape(question.section) + "." + str(question.order_number) + ")"
    parts[0] += "</b>"

    if not answer.transcript:
        parts.append("⚠️ Bu javob transkripsiya qilinmadi.")
        return "\n".join(parts)

    feedback_data = {}
    if answer.feedback:
        try:
            feedback_data = json.loads(answer.feedback)
        except json.JSONDecodeError:
            pass
    mistakes = feedback_data.get("mistakes", [])

    parts.append("🎙️ <b>Siz aytdingiz:</b>")
    parts.append(_annotate(answer.transcript, mistakes))

    if mistakes:
        parts.append("❌ <b>Xatolar: " + str(len(mistakes)) + " ta</b>")
        for i, m in enumerate(mistakes[:5], start=1):
            line = (
                str(i) + ". ❌ <s>" + html.escape(m.get("original") or "")
                + "</s> ➡️ ✅ <b>" + html.escape(m.get("correct") or "") + "</b>"
            )
            if m.get("explanation_uz") or m.get("explanation"):
                line += "\n   💬 " + html.escape(
                    m.get("explanation_uz") or m.get("explanation") or ""
                )
            parts.append(line)
    else:
        parts.append("✅ Xato topilmadi!")

    if answer.score is not None:
        if pts_info and pts_info["pts"]:
            parts.append(
                "⭐ <b>Ball: " + str(pts_info["earned"]) + "/" + str(pts_info["pts"]) + "</b>"
            )
        else:
            # Ball yozilmagan savol — foiz bilan ko'rsatiladi
            parts.append("⭐ <b>Ball: " + str(answer.score) + "%</b>")

    return "\n".join(parts)


async def _send_long(sender, chat_id: int, text: str) -> None:
    """Uzoq matnni bo'laklarga bo'lib yuboradi."""
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > MAX_MESSAGE_LEN:
            if current:
                await sender.send_message(chat_id, current)
            current = line[:MAX_MESSAGE_LEN]
        else:
            current = current + "\n" + line if current else line
    if current:
        await sender.send_message(chat_id, current)


async def _send_audio_safe(sender, chat_id: int, audio_path: Path, idx: int) -> None:
    """Audio yozuvni yuboradi — audio format qabul qilinmasa document sifatida."""
    caption = "🎧 Savol " + str(idx) + " javobi"
    await sender.send_audio(chat_id, audio_path, caption=caption)


# Duplicate report himoyasi: bitta attempt_id uchun faqat bir marta report yuboriladi.
_sent_reports: set[int] = set()
_SENT_REPORTS_MAX = 1000


async def _send_report(
    telegram_id: int,
    answers,
    questions: dict,
    total_earned: int,
    total_points: int,
    points_map: dict,
    attempt_id: int | None = None,
) -> None:
    """TelegramSender orqali hisobotni tartibli yuboradi.

    Barcha xabarlar (header, audio, text, summary) bitta sequential
    stream sifatida yuboriladi — ordering ta'minlangan.
    Bitta failed message butun queue'ni bloklamaydi.
    """
    from app.services.telegram_sender import telegram_sender

    # BUG FIX: `answers` `_process_attempt_and_report_inner`'dan `ordered`
    # sifatida keladi — bu ORM `Answer` obyektlari emas, oddiy dict'lar
    # ro'yxati (answers_data qurilishiga qarang). Pastdagi `_answer_text`
    # va shu funksiya `answer.transcript`, `answer.audio_path` kabi NUQTA
    # orqali murojaat qiladi — dict ustida bu har doim AttributeError
    # berardi va try/except ichida yutilib, foydalanuvchiga hech qanday
    # audio/transkript/xato tahlili yuborilmas edi (faqat header+summary).
    # Shu yerda dict'larni atributga ega obyektga o'giramiz — ORM
    # obyekt yoki test uchun FakeAnswer kelsa ham ta'sir qilmaydi.
    answers = [
        SimpleNamespace(**a) if isinstance(a, dict) else a
        for a in answers
    ]

    # Duplicate himoya
    if attempt_id is not None:
        if attempt_id in _sent_reports:
            logger.info("Report for attempt #%d already sent, skipping", attempt_id)
            return
        _sent_reports.add(attempt_id)
        # Tozalash — memory leak oldini olish
        if len(_sent_reports) > _SENT_REPORTS_MAX:
            _sent_reports.clear()

    chat_id = telegram_id
    level = _score_to_level(total_earned)

    # 1. Header
    header = (
        "🏁 <b>Test yakunlandi!</b>\n\n"
        "⏳ Javoblaringiz tahlil qilinmoqda...\n"
        "Har bir savol bo'yicha natija alohida yuboriladi."
    )
    await telegram_sender.send_message(chat_id, header)

    # 2. Har bir javob: audio + text
    total = len(answers)
    for idx, answer in enumerate(answers, start=1):
        try:
            # Audio
            audio_path = Path(answer.audio_path) if answer.audio_path else None
            if audio_path and audio_path.exists():
                await _send_audio_safe(telegram_sender, chat_id, audio_path, idx)

            # Text
            text = _answer_text(
                idx, total, answer,
                questions.get(answer.question_id),
                points_map.get(answer.id),
            )
            await _send_long(telegram_sender, chat_id, text)
        except Exception as e:
            # Bitta javob xatosi butun reportni to'xtatmasin
            logger.warning("Report message %d/%d failed (chat=%s): %s", idx, total, chat_id, e)

    # 3. Summary
    summary_lines = [
        "🎉 <b>Umumiy natija</b>",
        "",
        "⭐ Umumiy ball: <b>" + str(total_earned) + "/" + str(total_points) + "</b>",
    ]
    summary_lines.append(
        "📊 Daraja: <b>" + (level or "B1 talabiga yetmadi") + "</b>"
    )
    summary_lines.append("📝 Javoblar soni: <b>" + str(total) + "</b>")
    await telegram_sender.send_message(chat_id, "\n".join(summary_lines))