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
from app.services.user_scope import _USER_SELECTION
from app.utils.helpers import format_filename, utcnow

logger = logging.getLogger(__name__)

# Eksport qilingan hisobot fayllarining saqlanish papkasi (proyekt ildizi).
REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"


async def collect_users_with_results(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """`_USER_SELECTION` mezoni (is_admin=False va is_registered=True) ga
    mos keladigan barcha foydalanuvchilarni hamda ularning eng so'nggi
    test natijalarini (ball, daraja) yig'adi. Hisobotga faqat kamida
    bitta attempti bo'lganlar kiradi; hali test topshirmaganlar qator
    sifatida tushmaydi (lekin baribir `_USER_SELECTION` mezoni bo'yicha
    hisobga olinadi).
    """
    result = await session.execute(
        select(User).where(_USER_SELECTION())
    )
    users = list(result.scalars().all())

    # Foydalanuvchi IDlarini yig'ib, ularning barcha attemptlarini olamiz.
    # Masshtab kichik (~yuzlab foydalanuvchi), shuning uchun hammasini
    # bitta so'rovda olib, Python'da guruhlash amaliy.
    rows: list[dict[str, Any]] = []
    if not users:
        return rows

    # Hisobotga faqat natijasi (attempti) bo'lganlar kiradi.

    user_ids = [u.id for u in users]
    att_result = await session.execute(
        select(TestAttempt).where(TestAttempt.user_id.in_(user_ids))
    )
    attempts = list(att_result.scalars().all())

    attempts_by_user: dict[Any, list[TestAttempt]] = {}
    for attempt in attempts:
        attempts_by_user.setdefault(attempt.user_id, []).append(attempt)

    for user in users:
        user_attempts = attempts_by_user.get(user.id, [])
        if not user_attempts:
            continue
        # Eng so'nggi attempt — `started_at` bo'yicha eng kattasi.
        latest = max(user_attempts, key=lambda a: (a.started_at or utcnow()))
        rows.append(
            {
                "full_name": user.full_name or user.username or str(user.telegram_id),
                "score": latest.score,
                "level": latest.level,
            }
        )

    # Ism bo'yicha tartiblash (naklonistik, lekin amaliy jihatdan yetarli).
    rows.sort(key=lambda r: (r["full_name"] or "").lower())
    return rows


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

    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    header = table.rows[0].cells
    headers = ["#", "Ism Familiya", "Umumiy ball", "Daraja"]
    for i, text in enumerate(headers):
        header[i].text = text
        _style_header_cell(header[i])

    for idx, row in enumerate(rows, start=1):
        cells = table.add_row().cells
        cells[0].text = str(idx)
        cells[1].text = row["full_name"] or "—"
        cells[2].text = str(row["score"]) if row["score"] is not None else "—"
        cells[3].text = row["level"] or "—"

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
