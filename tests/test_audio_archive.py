"""
Audio javoblar va savol rasmlari O'CHIRILMAYDI — arxivga ko'chiriladi:
- kunlik wipe: barcha audio data/archive/<sana>_kunlik/<ism>_<tg>/<bo'lim>-<tartib>.webm,
  savol rasmlarining nusxasi savol_rasmlari/ ga
- blokdan chiqarish va 30 kunlik tozalash ham audio'ni arxivlaydi
- arxivlangan fayllarga "yetim audio" tozalashi tegmaydi
"""

import os
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.database.database import Base
from app.database.models import Answer, Question, TestAttempt, User
from app.services import cleanup_service
from app.services.base_wipe import wipe_user_data
from app.utils.helpers import utcnow

TEST_DB_URL = os.getenv(
    "TEST_DB_URL",
    "postgresql+asyncpg://postgres:123@localhost:5432/turkish_bot_test",
)
test_engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_db(tmp_path):
    db_name = TEST_DB_URL.split("?", 1)[0].rsplit("/", 1)[-1]
    if not db_name.endswith("_test"):
        raise RuntimeError(f"Xavfsizlik: TEST_DB_URL test bazasi emas ({db_name})")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    upload = tmp_path / "data" / "audios"
    upload.mkdir(parents=True)
    with patch.object(settings, "upload_dir", str(upload)):
        yield upload
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _attempt_with_audio(upload: Path, tg_id: int, name: str, started_days_ago: int = 0):
    async with TestSessionLocal() as s:
        user = User(telegram_id=tg_id, full_name=name, is_registered=True)
        q = Question(section="1.4", order_number=1, text="Soru?")
        s.add_all([user, q])
        await s.flush()
        attempt = TestAttempt(
            user_id=user.id, status="finished",
            started_at=utcnow() - timedelta(days=started_days_ago),
        )
        s.add(attempt)
        await s.flush()
        audio = upload / str(attempt.id) / "abc123.webm"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b"audio-bytes")
        s.add(Answer(attempt_id=attempt.id, question_id=q.id, audio_path=str(audio)))
        await s.commit()
        return user.id, attempt.id, audio


def _archived(upload: Path) -> list[Path]:
    root = upload.parent / "archive"
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


@pytest.mark.anyio
async def test_daily_wipe_archives_audio_and_images(setup_db):
    upload = setup_db
    _, _, audio = await _attempt_with_audio(upload, 860103732, "Ali Valiyev")
    (upload / "images").mkdir()
    (upload / "images" / "rId4.png").write_bytes(b"png")

    async with TestSessionLocal() as s:
        result = await wipe_user_data(s)

    assert result["audio_files"] == 1 and result["images"] == 1
    assert not audio.exists()
    files = _archived(upload)
    names = [str(p.relative_to(Path(result["archive_dir"]))) for p in files]
    assert "Ali_Valiyev_860103732/1.4-1.webm" in [n.replace("\\", "/") for n in names]
    assert "savol_rasmlari/rId4.png" in [n.replace("\\", "/") for n in names]
    archived_audio = next(p for p in files if p.suffix == ".webm")
    assert archived_audio.read_bytes() == b"audio-bytes"
    # Joriy savol rasmi joyida qoladi (nusxa olinadi, ko'chirilmaydi)
    assert (upload / "images" / "rId4.png").exists()
    async with TestSessionLocal() as s:
        assert (await s.execute(select(func.count()).select_from(Answer))).scalar() == 0


@pytest.mark.anyio
async def test_unblock_archives_audio(setup_db):
    upload = setup_db
    user_id, _, audio = await _attempt_with_audio(upload, 111, "Vali")
    async with TestSessionLocal() as s:
        res = await cleanup_service.delete_user_attempts(s, user_id)
    assert res == {"attempts": 1, "files": 1}
    assert not audio.exists()
    assert any("blokdan_chiqarilgan" in str(p) for p in _archived(upload))


@pytest.mark.anyio
async def test_old_attempt_cleanup_archives_audio(setup_db):
    upload = setup_db
    _, _, audio = await _attempt_with_audio(upload, 222, "Eski", started_days_ago=40)
    async with TestSessionLocal() as s:
        res = await cleanup_service.delete_old_attempts(s)
        await s.commit()
    assert res == {"attempts": 1, "files": 1}
    assert any("eski_testlar" in str(p) for p in _archived(upload))


@pytest.mark.anyio
async def test_orphan_cleanup_never_touches_archive(setup_db):
    upload = setup_db
    await _attempt_with_audio(upload, 333, "Arxiv")
    async with TestSessionLocal() as s:
        await wipe_user_data(s)
    archived = _archived(upload)
    old = 1_000_000_000  # juda eski mtime
    for p in archived:
        os.utime(p, (old, old))

    async with TestSessionLocal() as s:
        await cleanup_service.delete_orphan_audios(s)

    assert all(p.exists() for p in archived)
