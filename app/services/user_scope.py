from sqlalchemy import and_

from app.database.models import User


def _USER_SELECTION():
    """Eksport hisoboti va tozalash (wipe) o'rtasidagi YAGONA mezon.

    Ikkala jarayon aynan shu funksiyani chaqiradi, shuning uchun
    `is_registered=True` va `is_admin=False` mezoni hech qayerda
    takrorlanmaydi. Bu hisobotda ko'rinadiganlar va wipe'da o'chadiganlar
    o'rtasida nomuvofiqlikni strukturaviy yo'q qiladi.
    """
    return and_(
        User.is_admin.is_(False),
        User.is_registered.is_(True),
    )
