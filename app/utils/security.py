import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from app.config import settings


def _parse_init_data(init_data: str) -> dict | None:
    """initData ni dict ga aylantiradi va imzosini tekshiradi.

    Yaroqsiz imzo yoki noto'g'ri format bo'lsa None qaytaradi.
    """
    if not init_data:
        return None
    try:
        data = dict(parse_qsl(init_data))
    except Exception:
        return None

    received_hash = data.get("hash")
    if not received_hash:
        return None

    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(data.items())
        if key != "hash"
    )

    secret_key = hmac.new(
        b"WebAppData",
        settings.bot_token.encode(),
        hashlib.sha256,
    ).digest()

    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    return data


def validate_telegram_webapp_data(
    init_data: str,
) -> bool:
    """Telegram Web App initData imzosini tekshiradi."""
    return _parse_init_data(init_data) is not None


def get_telegram_user_id(init_data: str) -> int | None:
    """initData imzosini validatsiya qilib, undagi foydalanuvchi ID sini qaytaradi.

    Imzo yaroqsiz bo'lsa yoki user ma'lumoti bo'lmasa None qaytaradi.
    User ID faqat Telegram imzosi bilan tasdiqlangan initData dan olinadi.
    """
    data = _parse_init_data(init_data)
    if not data:
        return None

    user_raw = data.get("user")
    if not user_raw:
        return None

    try:
        user_obj = json.loads(user_raw)
    except (json.JSONDecodeError, TypeError):
        return None

    user_id = user_obj.get("id")
    if isinstance(user_id, int):
        return user_id
    return None