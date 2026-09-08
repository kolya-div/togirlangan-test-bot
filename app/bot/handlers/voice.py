"""Ovozli xabarlarni qabul qilish: transkripsiya + imlo tekshiruvi."""

import html
import logging
import re

from aiogram import F, Router
from aiogram.types import Message

from app.services.transcription_service import transcribe_audio_file
from app.services.text_check_service import check_turkish_text

logger = logging.getLogger(__name__)

router = Router()

MAX_MESSAGE_LEN = 4000
MAX_TELEGRAM_VOICE_MB = 20


@router.message(F.voice | F.audio)
async def voice_message_handler(message: Message) -> None:
    audio = message.voice or message.audio

    if hasattr(audio, "file_size") and audio.file_size:
        size_mb = audio.file_size / (1024 * 1024)
        if size_mb > MAX_TELEGRAM_VOICE_MB:
            try:
                await message.answer(
                    f"❌ Audio juda katta ({size_mb:.1f}MB). "
                    f"Maksimum {MAX_TELEGRAM_VOICE_MB}MB."
                )
            except Exception:
                pass
            return

    status = await message.answer(
        "🎙️ Ovoz yuklanmoqda va matnga aylantirilmoqda..."
    )

    try:
        transcript = await transcribe_audio_file(audio.file_id, message.bot)

        if not transcript or not transcript.strip():
            try:
                await status.edit_text(
                    "❌ Ovozingizni tushunolmadim. Iltimos, qaytadan gapiring."
                )
            except Exception:
                pass
            return

        await message.bot.send_chat_action(message.chat.id, "typing")
        result = await check_turkish_text(transcript)

        response = _format_response(transcript, result)
        await status.delete()
        await _send_long(message, response)

    except RuntimeError as e:
        logger.warning(f"Transkripsiya xatosi: {e}")
        try:
            await status.edit_text(
                "❌ Ovozni matnga aylantirib bo'lmadi. Keyinroq qaytadan urinib ko'ring."
            )
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"Ovozli xabarni qayta ishlashda xato: {e}")
        try:
            await status.edit_text(
                "❌ Xatolik yuz berdi. Keyinroq qaytadan urinib ko'ring."
            )
        except Exception:
            pass


def _format_response(transcript: str, result: dict) -> str:
    mistakes = result.get("mistakes", [])
    feedback = result.get("feedback_uz", "").strip()

    parts = []

    parts.append("🎙️ <b>Siz aytdingiz:</b>")
    parts.append(_annotate_transcript(transcript, mistakes))

    if mistakes:
        parts.append(f"\n❌ <b>Topilgan xatolar: {len(mistakes)} ta</b>\n")

        for i, m in enumerate(mistakes, start=1):
            line = (
                f"{i}. ❌ <s>{html.escape(m['original'])}</s>"
                f" ➡️ ✅ <b>{html.escape(m['correct'])}</b>"
            )
            if m.get("type") and m["type"].lower() != "xato":
                line += f"  ({html.escape(m['type'])})"
            explanation = m.get("explanation_uz", "")
            if explanation:
                line += f"\n   💬 {html.escape(explanation)}"
            parts.append(line + "\n")
    else:
        parts.append("\n✅ <b>Ajoyib! Barcha so'zlaringiz to'g'ri.</b>")

    corrected = result.get("corrected_text", "").strip()
    if corrected and corrected != transcript.strip():
        parts.append("✍️ <b>To'g'irlangan matn:</b>")
        parts.append(html.escape(corrected))

    if feedback:
        parts.append(f"\n💬 <b>Fikr:</b> {html.escape(feedback)}")

    return "\n".join(parts)


def _annotate_transcript(transcript: str, mistakes: list[dict]) -> str:
    text = html.escape(transcript.strip())

    for m in mistakes:
        original = m.get("original", "")
        correct = m.get("correct", "")
        if not original or original.lower() == correct.lower():
            continue

        pattern = re.compile(re.escape(html.escape(original)), re.IGNORECASE)
        replacement = f"<s>{html.escape(original)}</s>➡️<b>{html.escape(correct)}</b>"

        if pattern.search(text):
            text = pattern.sub(replacement, text, count=1)

    return text


async def _send_long(message: Message, text: str) -> None:
    chunks = []
    current = ""

    for part in text.split("\n"):
        if len(current) + len(part) + 1 > MAX_MESSAGE_LEN:
            if current:
                chunks.append(current)
            current = part[:MAX_MESSAGE_LEN]
        else:
            current = f"{current}\n{part}" if current else part

    if current:
        chunks.append(current)

    for chunk in chunks:
        await message.answer(chunk, parse_mode="HTML")
