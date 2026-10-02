import asyncio
import base64
import logging
import mimetypes
import random
from pathlib import Path

from app.config import settings
from app.services.ai_provider_base import (
    AIProvider,
    MultiKeyRotator,
    ProviderChain,
    create_gemini_rotator
)
from app.services.prompts import TRANSCRIPTION_SYSTEM_PROMPT
from app.services.rate_limiter import wait_gemini, wait_groq

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = {".webm", ".ogg", ".mp4", ".wav", ".mp3", ".m4a", ".oga"}
MIN_AUDIO_SIZE = 1024
TRANSCRIPTION_TIMEOUT = 120
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0
RATE_LIMIT_DELAY = 10.0


def _validate_audio_file(audio_path: Path) -> None:
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio fayl topilmadi: {audio_path.name}")

    if not audio_path.is_file():
        raise ValueError(f"Bu fayl emas: {audio_path.name}")

    size = audio_path.stat().st_size
    if size < MIN_AUDIO_SIZE:
        raise ValueError("Audio fayl bo'sh yoki juda kichik")

    max_size_mb = getattr(settings, "max_audio_size_mb", 20) or 20
    if size > max_size_mb * 1024 * 1024:
        raise ValueError(f"Audio fayl juda katta (maksimum {max_size_mb}MB)")

    ext = audio_path.suffix.lower()
    if ext and ext not in SUPPORTED_AUDIO_EXTENSIONS:
        raise ValueError(f"Qo'llab-quvvatlanmaydigan format: {ext}")


def _normalize_text(text: str) -> str:
    text = text.strip()
    text = " ".join(text.split())
    return text


def _is_valid_transcript(text: str) -> bool:
    if not text or len(text.strip()) < 2:
        return False
    if text.strip().upper() == "EMPTY":
        return False
    stripped = text.strip()
    if len(set(stripped.replace(" ", ""))) < 2:
        return False
    return True


def _detect_mime_type(audio_path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(audio_path))
    if mime and mime.startswith("audio/"):
        return mime
    ext_map = {
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
        ".mp4": "audio/mp4",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".oga": "audio/ogg",
    }
    return ext_map.get(audio_path.suffix.lower(), "audio/webm")


# Umumiy rotator: har chaqiruvda yangisini yaratish hisoblagichni 0 dan
# boshlardi — bir nechta kalit bo'lsa ham doim birinchisi ishlatilardi.
_gemini_rotator = None


def _get_gemini_rotator():
    global _gemini_rotator
    if _gemini_rotator is None:
        _gemini_rotator = create_gemini_rotator()
    return _gemini_rotator


async def _transcribe_with_gemini(audio_path: Path) -> str:
    from google import genai

    # Multi-key rotation: round-robin across available keys
    rotator = _get_gemini_rotator()
    api_key = await rotator.get_next_key() if rotator else None
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY sozlanmagan")

    await wait_gemini()

    client = genai.Client(api_key=api_key)

    audio_bytes = audio_path.read_bytes()
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    mime_type = _detect_mime_type(audio_path)

    # FIX: eski modellar yangi kalitlarda yopilgan → config.py dagi
    # ishlaydigan model ishlatiladi (default: gemini-3.6-flash).
    model = getattr(settings, "gemini_stt_model", "gemini-3.6-flash")

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=[
            {
                "parts": [
                    {"text": TRANSCRIPTION_SYSTEM_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": audio_b64,
                        }
                    },
                ]
            }
        ],
        # 0 — model "ijod" qilmasin, eshitilganini yozsin
        config={"temperature": 0},
    )

    result = response.text if response.text else ""
    return result


async def _transcribe_with_groq(audio_path: Path) -> str:
    from groq import AsyncGroq

    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY sozlanmagan")

    await wait_groq()

    client = AsyncGroq(
        api_key=settings.groq_api_key,
        timeout=TRANSCRIPTION_TIMEOUT,
    )

    with open(audio_path, "rb") as audio_file:
        transcription = await client.audio.transcriptions.create(
            file=audio_file,
            model=getattr(settings, "groq_stt_model", "whisper-large-v3-turbo"),
            language="tr",
            response_format="text",
        )

    return transcription


async def _try_provider(name: str, fn, audio_path: Path) -> str:
    """Bitta providerda MAX_RETRIES marta urinadi."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            result = await asyncio.wait_for(
                fn(audio_path),
                timeout=TRANSCRIPTION_TIMEOUT,
            )
            result = _normalize_text(result)

            if not _is_valid_transcript(result):
                logger.warning(
                    f"Transkripsiya natijasi yaroqsiz ({name}): "
                    f"{audio_path.name} (uzunlik={len(result)})"
                )
                return ""
            return result

        except asyncio.TimeoutError:
            last_error = "Timeout"
            logger.warning(
                f"Timeout ({name}), urinish {attempt + 1}/{MAX_RETRIES}: "
                f"{audio_path.name}"
            )
        except Exception as e:
            last_error = e
            err_str = str(e).lower()

            if any(kw in err_str for kw in ["429", "rate limit", "quota", "too many requests"]):
                delay = RATE_LIMIT_DELAY * (attempt + 1)
                logger.warning(
                    f"Rate limit ({name}), {delay}s kutiladi, "
                    f"urinish {attempt + 1}/{MAX_RETRIES}: {audio_path.name}"
                )
                await asyncio.sleep(delay)
                continue

            if any(kw in err_str for kw in ["400", "invalid", "unsupported", "auth"]):
                raise RuntimeError(f"Transkripsiya xatosi ({name}): {e}") from None

            logger.warning(
                f"Transkripsiya xatosi ({name}), "
                f"urinish {attempt + 1}/{MAX_RETRIES}: {e}"
            )

        if attempt < MAX_RETRIES - 1:
            delay = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
            await asyncio.sleep(delay)

    raise RuntimeError(f"Transkripsiya muvaffaqiyatsiz ({name}): {last_error}")


def _get_provider_chain() -> list[tuple[str, callable]]:
    """Asosiy provider birinchi, keyin fallback."""
    primary = getattr(settings, "stt_provider", "gemini")
    chain = []
    if primary == "gemini":
        chain.append(("gemini", _transcribe_with_gemini))
        if settings.groq_api_key:
            chain.append(("groq", _transcribe_with_groq))
    else:
        chain.append(("groq", _transcribe_with_groq))
        if settings.gemini_keys_list:
            chain.append(("gemini", _transcribe_with_gemini))
    return chain


async def transcribe_audio(audio_path: str | Path) -> str:
    audio_path = Path(audio_path)
    _validate_audio_file(audio_path)

    providers = _get_provider_chain()
    provider_chain = ProviderChain(providers)
    
    try:
        result = await provider_chain.execute(audio_path)
        return result
    except RuntimeError as e:
        logger.error(f"Transkripsiya xizmati vaqtincha ishlamayapti: {e}")
        raise


async def transcribe_audio_file(file_id: str, bot, download_dir: str = "data/audios") -> str:
    download_dir = Path(download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)

    # FIX #5: Avval har doim .ogg kengaytmasi ishlatilardi —
    # audio (mp3, m4a va b.) uchun MIME type noto'g'ri aniqlanardi.
    # Endi Telegram'dan haqiqiy fayl yo'li olinib, uning kengaytmasi ishlatiladi.
    file = await bot.get_file(file_id)
    original_ext = Path(file.file_path).suffix if file.file_path else ".ogg"
    if not original_ext or original_ext not in SUPPORTED_AUDIO_EXTENSIONS:
        original_ext = ".ogg"  # Fallback — voice xabar odatda .oga/.ogg

    file_path = download_dir / f"{file_id}{original_ext}"

    try:
        await bot.download_file(file.file_path, destination=file_path)

        _validate_audio_file(file_path)

        return await transcribe_audio(file_path)

    finally:
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass