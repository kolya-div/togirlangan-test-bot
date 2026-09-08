from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards import phone_keyboard
from app.bot.states import RegistrationStates
from app.config import settings
from app.database.database import SessionLocal
from app.database.repositories import get_or_create_user


router = Router()


@router.message(Command("register"))
async def start_registration(
    message: Message,
    state: FSMContext,
) -> None:
    async with SessionLocal() as session:
        user = await get_or_create_user(
            session=session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
            admin_ids=settings.admin_id_list,
        )

        if user.is_admin:
            await message.answer("Siz adminsiz. Ro'yxatdan o'tish shart emas.")
            return

        if user.is_registered:
            await message.answer("Siz allaqachon ro'yxatdan o'tgansiz.")
            return

    await message.answer(
        "Ismingiz va familiyangizni kiriting:",
    )
    await state.set_state(RegistrationStates.waiting_full_name)


@router.message(RegistrationStates.waiting_full_name)
async def process_full_name(
    message: Message,
    state: FSMContext,
) -> None:
    full_name = message.text.strip()

    if len(full_name) < 3:
        await message.answer(
            "Ism va familiya juda qisqa. Qayta kiriting:",
        )
        return

    await state.update_data(full_name=full_name)
    await message.answer(
        "Telefon raqamingizni yuboring:",
        reply_markup=phone_keyboard(),
    )
    await state.set_state(RegistrationStates.waiting_phone)


@router.message(
    RegistrationStates.waiting_phone,
    F.contact,
)
async def process_phone(
    message: Message,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    full_name = data.get("full_name")
    phone = message.contact.phone_number

    async with SessionLocal() as session:
        user = await get_or_create_user(
            session=session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=full_name,
            admin_ids=settings.admin_id_list,
        )

        user.phone = phone
        user.is_registered = True

        await session.commit()

    await state.clear()

    await message.answer(
        "✅ Ro'yxatdan o'tdingiz.\nAdmin testni faollashtirishini kuting.",
        reply_markup=None,
    )