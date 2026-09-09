import logging
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TestAttempt, User
from app.utils.helpers import format_filename, utcnow

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
                }
            )

    # Ism bo'yicha tartiblash (naklonistik, lekin amaliy jihatdan yetarli).
    rows.sort(key=lambda r: (r["full_name"] or "").lower())
    return rows


def _fmt_dt(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "*"


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
    run = subtitle.add_run(f"Hisobot sanasi: {utcnow():%Y-%m-%d %H:%M}")
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
        cells[2].text = row["full_name"] or "—"
        cells[3].text = row["username"] or "—"
        cells[4].text = row["phone"] or "—"
        cells[5].text = _fmt_dt(row["created_at"])
        cells[6].text = row["status"] or "—"
        cells[7].text = _fmt_dt(row["started_at"])
        cells[8].text = _fmt_dt(row["finished_at"])
        cells[9].text = str(row["score"]) if row["score"] is not None else "—"
        cells[10].text = row["level"] or "—"

    doc.save(str(file_path))
    logger.info("Hisobot fayli saqlandi: %s (%s qator)", file_path, len(rows))


def default_report_path() -> Path:
    """Hozirgi vaqtga asoslangan hisobot fayli yo'li."""
    name = format_filename(f"users_report_{utcnow():%Y%m%d_%H%M%S}")
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
