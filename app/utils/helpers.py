import logging
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# Asia/Tashkent — UTC+5, yozgi vaqt yo'q. Windows'da tzdata o'rnatilmagan
# bo'lsa ZoneInfo ishlamaydi — shunda shu qat'iy offset ishlatiladi.
_FALLBACK_TZ = timezone(timedelta(hours=5), "UTC+05")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@lru_cache
def local_tz() -> tzinfo:
    """Hisobotlar uchun vaqt mintaqasi (REPORT_TIMEZONE, default Asia/Tashkent)."""
    from app.config import settings

    name = getattr(settings, "report_timezone", "Asia/Tashkent")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Vaqt mintaqasi %r topilmadi — UTC+5 ishlatiladi", name)
        return _FALLBACK_TZ


def local_now() -> datetime:
    """Mahalliy vaqt (timezone-aware)."""
    return datetime.now(local_tz())


def to_local(value: datetime | None) -> datetime | None:
    """DB dagi naive UTC vaqtni mahalliy vaqtga o'giradi."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(local_tz())


def seconds_until_local_midnight() -> float:
    """Keyingi mahalliy 00:00 gacha qolgan soniyalar."""
    now = local_now()
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (midnight - now).total_seconds()


def format_timedelta(td: timedelta) -> str:
    hours, remainder = divmod(int(td.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def format_filename(name: str) -> str:
    return "".join(
        c for c in name if c.isalnum() or c in "._-"
    ).strip()