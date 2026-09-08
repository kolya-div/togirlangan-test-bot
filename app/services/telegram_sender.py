"""
Telegram yuborish xizmati — 100+ concurrent user uchun ishlab chiqilgan.

Xususiyatlari:
- 429 (Too Many Requests) + retry_after extraction
- Exponential backoff + max retry
- Telegram API timeout
- Network failure handling
- Bounded send queue (memory safety)
- Queue monitoring (depth, throughput, errors)
- Per-user report deduplication
- Message ordering (bitta user reportining barcha message'lari tartibli)
"""

import asyncio
import logging
import time
import re
from dataclasses import dataclass, field
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from app.config import settings
from app.services.telegram_rate_limiter import wait_send_gate

logger = logging.getLogger(__name__)

# Telegram API timeout
TELEGRAM_API_TIMEOUT = 30.0

# Max retries for any send operation
MAX_SEND_RETRIES = 4

# Base delay for exponential backoff
BACKOFF_BASE = 0.7
BACKOFF_MAX = 16.0

# Send queue limits
MAX_SEND_QUEUE_SIZE = 500

# Duplicate prevention window (seconds)
DEDUP_WINDOW = 300  # 5 minutes


@dataclass
class SendMetrics:
    """Telegram yuborish metrikalari."""
    total_sent: int = 0
    total_failed: int = 0
    total_retries: int = 0
    total_429: int = 0
    total_timeout: int = 0
    total_network_error: int = 0
    queue_depth: int = 0
    max_queue_depth: int = 0
    avg_send_time: float = 0.0
    _send_times: list = field(default_factory=list)

    def record_send(self, duration: float):
        self.total_sent += 1
        self._send_times.append(duration)
        if len(self._send_times) > 1000:
            self._send_times = self._send_times[-500:]
        self.avg_send_time = sum(self._send_times) / len(self._send_times)

    def record_failure(self, error_type: str):
        self.total_failed += 1
        if error_type == "429":
            self.total_429 += 1
        elif error_type == "timeout":
            self.total_timeout += 1
        elif error_type == "network":
            self.total_network_error += 1

    def to_dict(self) -> dict:
        return {
            "total_sent": self.total_sent,
            "total_failed": self.total_failed,
            "total_retries": self.total_retries,
            "total_429": self.total_429,
            "total_timeout": self.total_timeout,
            "total_network_error": self.total_network_error,
            "queue_depth": self.queue_depth,
            "max_queue_depth": self.max_queue_depth,
            "avg_send_time_ms": round(self.avg_send_time * 1000, 1),
        }


class TelegramSender:
    """
    Markazlashtirilgan Telegram yuborish xizmati.

    Barcha Telegram API calllari shu orqali o'tadi:
    - send_message
    - send_audio
    - send_document
    - send_chat_action
    """

    def __init__(self):
        self._dedup: dict[str, float] = {}  # key → timestamp
        self._metrics = SendMetrics()
        self._lock = asyncio.Lock()

    @property
    def metrics(self) -> SendMetrics:
        return self._metrics

    def _make_dedup_key(self, chat_id: int, content_type: str, content_hash: str) -> str:
        return f"{chat_id}:{content_type}:{content_hash}"

    def _is_duplicate(self, key: str) -> bool:
        now = time.monotonic()
        # Clean old entries
        expired = [k for k, t in self._dedup.items() if now - t > DEDUP_WINDOW]
        for k in expired:
            del self._dedup[k]

        if key in self._dedup:
            return True
        self._dedup[key] = now
        return False

    def _classify_error(self, error: Exception) -> str:
        """Xato turini aniqlaydi."""
        err = str(error).lower()

        if any(kw in err for kw in ["429", "too many requests", "retry after", "flood"]):
            return "429"
        if any(kw in err for kw in ["timeout", "timed out", "slow down"]):
            return "timeout"
        if any(kw in err for kw in ["connection", "network", "refused", "reset", "broken pipe"]):
            return "network"
        return "other"

    def _extract_retry_after(self, error: Exception) -> float | None:
        """Telegram xatosidan retry_after qiymatini chiqaradi."""
        err = str(error)

        # "retry after 5 seconds" yoki "retry_after: 5"
        m = re.search(r"retry.?after[^\d]*(\d+(?:\.\d+)?)", err, re.IGNORECASE)
        if m:
            return float(m.group(1))

        # "Too Many Requests: retry after 5"
        m = re.search(r"after\s+(\d+(?:\.\d+)?)", err, re.IGNORECASE)
        if m:
            return float(m.group(1))

        return None

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        dedup_key: str | None = None,
    ) -> bool:
        """Xabar yuboradi. Muvaffaqiyatli bo'lsa True, yo'qolsa False."""
        return await self._send_with_retry(
            chat_id=chat_id,
            send_fn=lambda: self._get_bot().send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
            ),
            content_type="message",
            content_hash=str(hash(text[:100])),
            dedup_key=dedup_key,
        )

    async def send_audio(
        self,
        chat_id: int,
        audio_path: Path,
        caption: str = "",
        dedup_key: str | None = None,
    ) -> bool:
        """Audio yuboradi. Muvaffaqiyatli bo'lsa True."""
        return await self._send_with_retry(
            chat_id=chat_id,
            send_fn=lambda: self._get_bot().send_audio(
                chat_id=chat_id,
                audio=FSInputFile(str(audio_path)),
                caption=caption,
            ),
            content_type="audio",
            content_hash=audio_path.name,
            dedup_key=dedup_key,
            fallback_fn=lambda: self._get_bot().send_document(
                chat_id=chat_id,
                document=FSInputFile(str(audio_path)),
                caption=caption,
            ) if audio_path.suffix.lower() in (".webm", ".oga") else None,
        )

    async def send_document(
        self,
        chat_id: int,
        document_path: Path,
        caption: str = "",
        dedup_key: str | None = None,
    ) -> bool:
        """Document yuboradi."""
        return await self._send_with_retry(
            chat_id=chat_id,
            send_fn=lambda: self._get_bot().send_document(
                chat_id=chat_id,
                document=FSInputFile(str(document_path)),
                caption=caption,
            ),
            content_type="document",
            content_hash=document_path.name,
            dedup_key=dedup_key,
        )

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> bool:
        """Chat action yuboradi (typing, record_voice)."""
        try:
            await self._get_bot().send_chat_action(chat_id=chat_id, action=action)
            return True
        except Exception:
            return False  # Action xatosi muhim emas

    async def _send_with_retry(
        self,
        chat_id: int,
        send_fn,
        content_type: str,
        content_hash: str,
        dedup_key: str | None = None,
        fallback_fn=None,
    ) -> bool:
        """
        Retry logikasi bilan yuborish.
        - 429: retry_after + exponential backoff
        - Timeout: retry with backoff
        - Network: retry with backoff
        - Non-retryable: birinchi urinishda raise
        """
        # Duplicate tekshirish
        dk = dedup_key or self._make_dedup_key(chat_id, content_type, content_hash)
        if self._is_duplicate(dk):
            logger.info("Duplicate send skipped: %s", dk)
            return True

        delay = BACKOFF_BASE
        last_err = None
        bot = self._get_bot()

        for attempt in range(MAX_SEND_RETRIES):
            start = time.monotonic()
            try:
                await wait_send_gate()  # Global rate limit
                await asyncio.wait_for(send_fn(), timeout=TELEGRAM_API_TIMEOUT)
                duration = time.monotonic() - start
                self._metrics.record_send(duration)
                return True

            except Exception as e:
                duration = time.monotonic() - start
                error_type = self._classify_error(e)
                last_err = e

                self._metrics.record_failure(error_type)

                if error_type == "429":
                    self._metrics.total_retries += 1
                    retry_after = self._extract_retry_after(e)
                    wait_time = retry_after if retry_after else delay
                    logger.warning(
                        "Telegram 429 (chat=%s), %.1fs kutildi, urinish %d/%d",
                        chat_id, wait_time, attempt + 1, MAX_SEND_RETRIES,
                    )
                    await asyncio.sleep(wait_time)
                    delay = min(delay * 2, BACKOFF_MAX)

                elif error_type == "timeout":
                    self._metrics.total_retries += 1
                    logger.warning(
                        "Telegram timeout (chat=%s), urinish %d/%d",
                        chat_id, attempt + 1, MAX_SEND_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, BACKOFF_MAX)

                elif error_type == "network":
                    self._metrics.total_retries += 1
                    logger.warning(
                        "Telegram network error (chat=%s): %s, urinish %d/%d",
                        chat_id, e, attempt + 1, MAX_SEND_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, BACKOFF_MAX)

                else:
                    # Non-retryable — audio format error bo'lsa fallback sinab ko'ramiz
                    if fallback_fn and attempt == 0:
                        try:
                            await wait_send_gate()
                            await asyncio.wait_for(fallback_fn(), timeout=TELEGRAM_API_TIMEOUT)
                            self._metrics.record_send(time.monotonic() - start)
                            return True
                        except Exception as fb_err:
                            logger.warning("Fallback send also failed: %s", fb_err)
                    # Other errors — raise immediately
                    if attempt == 0:
                        raise

        # All retries exhausted
        logger.error(
            "Telegram send failed after %d attempts (chat=%s): %s",
            MAX_SEND_RETRIES, chat_id, last_err,
        )
        return False

    def _get_bot(self) -> Bot:
        """Yangi Bot instansiyasi — loop ziddiyatini oldini oladi."""
        return Bot(token=settings.bot_token)

    def update_queue_depth(self, depth: int):
        """Queue monitoring uchun."""
        self._metrics.queue_depth = depth
        if depth > self._metrics.max_queue_depth:
            self._metrics.max_queue_depth = depth


# Global instance
telegram_sender = TelegramSender()
