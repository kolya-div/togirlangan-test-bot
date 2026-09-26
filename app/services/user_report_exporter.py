import json
import logging
import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Answer, Question, TestAttempt, User
from app.utils.helpers import format_filename, local_now, to_local

logger = logging.getLogger(__name__)

# Eksport qilingan hisobot fayllarining saqlanish papkasi (proyekt ildizi).
REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"


async def collect_users_with_results(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """BARCHA foydalanuvchilar (adminlar ham) va ularning barcha test
    attemptlarini to'liq ma'lumot bilan yig'adi.

    Wipe (to'liq tozalash) oldidan YAGONA ma'lumot manbai — .docx hisobot.
    Shuning uchun hech narsa filtirlanmaydi: har bir attempt alohida qator
    bo'ladi, test topshirmagan userlar ham "test topshirmagan" holatida
    kiradi (ularning to'liq ma'lumoti yo'qolmasligi uchun).
    """
    result = await session.execute(select(User).order_by(User.id))
    users = list(result.scalars().all())

    rows: list[dict[str, Any]] = []
    if not users:
        return rows

    user_ids = [u.id for u in users]
    att_result = await session.execute(
        select(TestAttempt).where(TestAttempt.user_id.in_(user_ids)).order_by(TestAttempt.id)
    )
    attempts = list(att_result.scalars().all())

    answers_by_attempt = await _collect_answers(session, [a.id for a in attempts])

    attempts_by_user: dict[Any, list[TestAttempt]] = {}
    for attempt in attempts:
        attempts_by_user.setdefault(attempt.user_id, []).append(attempt)

    for user in users:
        user_attempts = attempts_by_user.get(user.id, [])
        if not user_attempts:
            rows.append(
                {
                    "telegram_id": user.telegram_id,
                    "full_name": user.full_name or "*",
                    "username": user.username or "*",
                    "phone": user.phone or "*",
                    "created_at": user.created_at,
                    "status": "test topshirmagan",
                    "started_at": None,
                    "finished_at": None,
                    "score": None,
                    "level": None,
                    "answers": [],
                }
            )
            continue
        for attempt in user_attempts:
            rows.append(
                {
                    "telegram_id": user.telegram_id,
                    "full_name": user.full_name or "*",
                    "username": user.username or "*",
                    "phone": user.phone or "*",
                    "created_at": user.created_at,
                    "status": attempt.status,
                    "started_at": attempt.started_at,
                    "finished_at": attempt.finished_at,
                    "score": attempt.score,
                    "level": attempt.level,
                    "answers": answers_by_attempt.get(attempt.id, []),
                }
            )

    # Ism bo'yicha tartiblash (naklonistik, lekin amaliy jihatdan yetarli).
    rows.sort(key=lambda r: (r["full_name"] or "").lower())
    return rows


async def _collect_answers(
    session: AsyncSession,
    attempt_ids: list[int],
) -> dict[int, list[dict[str, Any]]]:
    """Har bir attempt uchun javoblar: savol, transkript, ball, xatolar.
    Savol tartibida (bo'lim, raqam) qaytariladi."""
    if not attempt_ids:
        return {}

    result = await session.execute(
        select(Answer, Question)
        .join(Question, Answer.question_id == Question.id, isouter=True)
        .where(Answer.attempt_id.in_(attempt_ids))
        .order_by(Answer.attempt_id, Question.section, Question.order_number)
    )

    by_attempt: dict[int, list[dict[str, Any]]] = {}
    for answer, question in result.all():
        feedback: dict[str, Any] = {}
        if answer.feedback:
            try:
                feedback = json.loads(answer.feedback)
            except (json.JSONDecodeError, TypeError):
                feedback = {}

        max_points = question.max_points if question else None
        earned = None
        if max_points and answer.score is not None:
            # report_service bilan bir xil hisob: foiz → savol balli
            earned = round(answer.score * max_points / 100)

        by_attempt.setdefault(answer.attempt_id, []).append(
            {
                "section": question.section if question else "",
                "order_number": question.order_number if question else 0,
                "question": question.text if question else "(savol o'chirilgan)",
                "transcript": answer.transcript or feedback.get("transcript") or "",
                "corrected_text": feedback.get("corrected_text") or "",
                "mistakes": feedback.get("mistakes") or [],
                "score": answer.score,
                "max_points": max_points,
                "earned": earned,
            }
        )
    return by_attempt


# XML (Word) da ruxsat etilmagan boshqaruv belgilari: \t, \n, \r dan tashqari.
# Bitta shunday belgi (ism yoki AI transkriptida) python-docx'da ValueError
# beradi va butun kunlik hisobot yuborilmay qoladi.
_XML_INVALID_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _clean(value: Any) -> str:
    """Matnni Word uchun xavfsiz qiladi."""
    if value is None:
        return ""
    return _XML_INVALID_RE.sub("", str(value))


def _fmt_dt(value) -> str:
    local = to_local(value)
    return local.strftime("%Y-%m-%d %H:%M") if local else "*"


def _fmt_answer_score(item: dict[str, Any]) -> str:
    if item["score"] is None:
        return "baholanmagan"
    if item["max_points"]:
        return f"{item['earned']}/{item['max_points']}"
    return f"{item['score']}%"


def _add_answers_section(doc, rows: list[dict[str, Any]]) -> None:
    """Har bir foydalanuvchining javoblari: savol, aytgani, xatolar, ball."""
    with_answers = [r for r in rows if r["answers"]]
    if not with_answers:
        return

    doc.add_page_break()
    doc.add_heading("Foydalanuvchilar javoblari", level=1)

    for row in with_answers:
        score = f"{row['score']}/75" if row["score"] is not None else "—"
        doc.add_heading(
            _clean(
                f"{row['full_name']} (@{row['username']}, ID {row['telegram_id']}) — "
                f"ball: {score}, daraja: {row['level'] or '—'}"
            ),
            level=2,
        )

        for idx, item in enumerate(row["answers"], start=1):
            q = doc.add_paragraph()
            q.add_run(
                _clean(f"{idx}. Savol ({item['section']}.{item['order_number']}): ")
            ).font.bold = True
            q.add_run(_clean(item["question"]))

            said = doc.add_paragraph()
            said.add_run("Aytgani: ").font.bold = True
            said.add_run(_clean(item["transcript"]) or "(transkripsiya qilinmadi)")

            if item["corrected_text"] and item["corrected_text"] != item["transcript"]:
                corrected = doc.add_paragraph()
                corrected.add_run("To'g'ri varianti: ").font.bold = True
                corrected.add_run(_clean(item["corrected_text"]))

            mistakes = [m for m in item["mistakes"] if isinstance(m, dict)]
            if mistakes:
                doc.add_paragraph().add_run(
                    f"Xatolar ({len(mistakes)} ta):"
                ).font.bold = True
                for m in mistakes:
                    line = f"{m.get('original') or ''} → {m.get('correct') or ''}"
                    explanation = m.get("explanation_uz") or m.get("explanation")
                    if explanation:
                        line += f" — {explanation}"
                    doc.add_paragraph(_clean(line), style="List Bullet")

            score_p = doc.add_paragraph()
            score_p.add_run("Ball: ").font.bold = True
            score_p.add_run(_fmt_answer_score(item))


def _style_header_cell(cell) -> None:
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.font.bold = True
            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)


def build_report_docx(
    rows: list[dict[str, Any]],
    file_path: Path,
) -> None:
    """Foydalanuvchilar va natijalari jadvalini o'z ichiga olgan .docx
    faylini yaratadi va `file_path` ga saqlaydi."""
    file_path.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()

    heading = doc.add_heading("Foydalanuvchilar va test natijalari", level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(f"Hisobot sanasi: {local_now():%Y-%m-%d %H:%M}")
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    if not rows:
        doc.add_paragraph("Hech qanday test natijasi topilmadi.")
        doc.save(str(file_path))
        return

    summary = doc.add_paragraph()
    summary.add_run(
        f"Jami: {len(rows)} ta foydalanuvchi natijasi"
    ).font.bold = True

    table = doc.add_table(rows=1, cols=11)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    header = table.rows[0].cells
    headers = [
        "#", "Telegram ID", "Ism Familiya", "Username", "Telefon",
        "Ro'yxat sanasi", "Holat", "Boshlangan", "Yakunlangan", "Ball", "Daraja",
    ]
    for i, text in enumerate(headers):
        header[i].text = text
        _style_header_cell(header[i])

    for idx, row in enumerate(rows, start=1):
        cells = table.add_row().cells
        cells[0].text = str(idx)
        cells[1].text = str(row["telegram_id"])
        cells[2].text = _clean(row["full_name"]) or "—"
        cells[3].text = _clean(row["username"]) or "—"
        cells[4].text = _clean(row["phone"]) or "—"
        cells[5].text = _fmt_dt(row["created_at"])
        cells[6].text = _clean(row["status"]) or "—"
        cells[7].text = _fmt_dt(row["started_at"])
        cells[8].text = _fmt_dt(row["finished_at"])
        cells[9].text = str(row["score"]) if row["score"] is not None else "—"
        cells[10].text = _clean(row["level"]) or "—"

    _add_answers_section(doc, rows)

    doc.save(str(file_path))
    logger.info("Hisobot fayli saqlandi: %s (%s qator)", file_path, len(rows))


def default_report_path() -> Path:
    """Hozirgi vaqtga asoslangan hisobot fayli yo'li."""
    name = format_filename(f"users_report_{local_now():%Y%m%d_%H%M%S}")
    return REPORTS_DIR / f"{name}.docx"


async def export_users_report(
    session: AsyncSession,
    file_path: Path | None = None,
) -> Path:
    """Barcha foydalanuvchilar natijalarini .docx hisobotga eksport qiladi
    va fayl yo'lini qaytaradi."""
    rows = await collect_users_with_results(session)
    target = file_path or default_report_path()
    build_report_docx(rows, target)
    return target
