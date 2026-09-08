from pathlib import Path
from zipfile import ZipFile
import re

from docx import Document
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Question


SECTION_RE = re.compile(r"^Bölüm\s+(.+)$", re.IGNORECASE)
QUESTION_RE = re.compile(
    r"^(?:\d+\.)?soru\s*:\s*(.*)$",
    re.IGNORECASE,
)
PREP_RE = re.compile(
    r"^Tayyorlanish\s*:\s*(\d+)$",
    re.IGNORECASE,
)
ANSWER_RE = re.compile(
    r"^Javob\s*:\s*(\d+)$",
    re.IGNORECASE,
)


def extract_docx_lines(path: str) -> list[str]:
    """DOCX fayldan matnli qatorlarni ajratib oladi."""
    document = Document(path)
    lines: list[str] = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            lines.append(text)

    return lines


def extract_docx_images(
    docx_path: str,
    output_dir: str,
) -> list[str]:
    """DOCX fayldan rasmlarni ajratib, papkaga saqlaydi."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    image_paths = []

    with ZipFile(docx_path) as archive:
        for name in archive.namelist():
            if name.startswith("word/media/"):
                filename = Path(name).name
                destination = output / filename
                destination.write_bytes(archive.read(name))
                image_paths.append(str(destination))

    return image_paths


async def import_questions_from_docx(
    session: AsyncSession,
    docx_path: str,
    images_dir: str | None = None,
) -> int:
    """DOCX fayldan savollarni bazaga import qiladi."""
    lines = extract_docx_lines(docx_path)

    if images_dir:
        extract_docx_images(docx_path, images_dir)

    section: str | None = None
    current_text: str | None = None
    preparation = 0
    answer_seconds = 0
    order_number = 0
    imported = 0

    for line in lines:
        section_match = SECTION_RE.match(line)
        if section_match:
            section = section_match.group(1).strip()
            order_number = 0
            continue

        question_match = QUESTION_RE.match(line)
        if question_match:
            current_text = question_match.group(1).strip()
            continue

        prep_match = PREP_RE.match(line)
        if prep_match:
            preparation = int(prep_match.group(1))
            continue

        answer_match = ANSWER_RE.match(line)
        if answer_match and current_text and section:
            answer_seconds = int(answer_match.group(1))
            order_number += 1

            session.add(
                Question(
                    section=section,
                    order_number=order_number,
                    text=current_text,
                    preparation_seconds=preparation,
                    answer_seconds=answer_seconds,
                ),
            )

            imported += 1
            current_text = None

    await session.commit()
    return imported