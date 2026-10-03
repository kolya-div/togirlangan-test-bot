"""Admin'ga yuboriladigan namuna Word fayl bizning parser bilan to'g'ri o'qiladi."""

import pytest

from app.services.docx_parser import parse_docx_questions
from app.services.docx_template import build_questions_template


@pytest.mark.anyio
async def test_template_parses_with_points_times_images_and_table(tmp_path):
    path = build_questions_template(tmp_path / "namuna.docx")
    questions = await parse_docx_questions(path, upload_dir=str(tmp_path / "up"))

    assert [q["section"] for q in questions] == ["1.1", "1.2", "1.3", "2", "3"]
    assert sum(q["points"] for q in questions) == 75
    assert [(q["prep_time"], q["answer_time"]) for q in questions][-1] == (60, 120)
    assert questions[2]["image_path"] and questions[3]["image_path"]
    assert questions[0]["image_path"] is None
    assert questions[4]["pro_points"] and questions[4]["con_points"]


@pytest.mark.anyio
async def test_upload_docx_button_sends_template(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.bot.handlers import admin
    from app.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "audios"))
    monkeypatch.setattr(admin, "_safe_edit", AsyncMock())
    cb = MagicMock()
    cb.from_user = SimpleNamespace(id=settings.admin_id_list[0])
    cb.answer = AsyncMock()
    cb.message.answer_document = AsyncMock()
    state = MagicMock(set_state=AsyncMock())

    await admin.upload_docx_handler(cb, state)

    sent = cb.message.answer_document.await_args.args[0]
    assert sent.filename == "savollar_namuna.docx"
    assert (tmp_path / "exports" / "savollar_namuna.docx").exists()
