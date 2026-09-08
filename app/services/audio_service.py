import os
from pathlib import Path

from app.config import settings


def get_audio_path(filename: str) -> Path:
    return Path(settings.upload_dir) / filename


def audio_exists(filename: str) -> bool:
    return get_audio_path(filename).exists()


def delete_audio_file(filename: str) -> bool:
    path = get_audio_path(filename)
    if path.exists():
        path.unlink()
        return True
    return False


def delete_all_audio_files() -> int:
    upload_dir = Path(settings.upload_dir)
    if not upload_dir.exists():
        return 0

    deleted = 0
    for file in upload_dir.glob("*"):
        if file.is_file():
            file.unlink()
            deleted += 1

    return deleted