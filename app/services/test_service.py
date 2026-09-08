import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Answer, Question, TestAttempt
from app.database.repositories import get_all_questions
from app.utils.helpers import utcnow

logger = logging.getLogger(__name__)


async def start_test(session: AsyncSession, user_id: int) -> TestAttempt:
    """Yangi test sessiyasini boshlash."""
    attempt = TestAttempt(
        user_id=user_id,
        status="started",
        started_at=utcnow(),
    )
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return attempt


async def get_test_questions(session: AsyncSession) -> list[Question]:
    """Barcha faol savollarni olish."""
    questions = await get_all_questions(session)
    return [q for q in questions if q.is_active]


async def save_answer(
    session: AsyncSession,
    attempt_id: int,
    question_id: int,
    audio_path: str | None = None,
    transcript: str | None = None,
    score: int | None = None,
    feedback: str | None = None,
) -> Answer:
    """Javobni saqlash."""
    answer = Answer(
        attempt_id=attempt_id,
        question_id=question_id,
        audio_path=audio_path,
        transcript=transcript,
        score=score,
        feedback=feedback,
    )
    session.add(answer)
    await session.commit()
    await session.refresh(answer)
    return answer


async def finish_test(
    session: AsyncSession,
    attempt: TestAttempt,
    total_score: int,
    level: str,
) -> TestAttempt:
    """Testni yakunlash."""
    attempt.status = "finished"
    attempt.score = total_score
    attempt.level = level
    attempt.finished_at = utcnow()
    
    await session.commit()
    await session.refresh(attempt)
    return attempt


def format_question_for_webapp(question: Question) -> dict:
    """Savolni Web App uchun JSON formatga o'tkazish."""
    sub_questions = None
    if question.sub_questions:
        try:
            sub_questions = json.loads(question.sub_questions)
        except (json.JSONDecodeError, TypeError):
            sub_questions = None
    
    return {
        "id": question.id,
        "section": question.section,
        "order": question.order_number,
        "text": question.text,
        "prep_time": question.preparation_seconds,
        "answer_time": question.answer_seconds,
        "image_url": f"/audios/images/{question.image_path}" if question.image_path else None,
        "sub_questions": sub_questions,
    }