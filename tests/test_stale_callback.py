"""Eskirgan tugma bosilishi (callback javob muddati o'tgan) xatosi logni
traceback bilan to'ldirmaydi, boshqa Telegram xatolari esa yashirilmaydi."""

from datetime import datetime

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot import handlers


def _dispatcher(error_text: str) -> Dispatcher:
    router = Router()

    @router.callback_query()
    async def failing(callback: CallbackQuery) -> None:
        raise TelegramBadRequest(
            method=AnswerCallbackQuery(callback_query_id=callback.id),
            message=error_text,
        )

    # Xuddi shu handler va filtrlar (handlers_router dagi bilan bir xil)
    observer = handlers.handlers_router.errors
    for h in observer.handlers:
        router.errors.register(h.callback, *[f.callback for f in h.filters])

    dp = Dispatcher()
    dp.include_router(router)
    return dp


def _update() -> Update:
    user = User(id=1, is_bot=False, first_name="A")
    msg = Message(message_id=1, date=datetime.now(), chat=Chat(id=1, type="private"), text="x")
    return Update(update_id=1, callback_query=CallbackQuery(
        id="q1", from_user=user, chat_instance="c", data="deactivate_test", message=msg,
    ))


BOT = Bot(token="123456:TESTtokenABCDEFGHIJKLMNOPQRSTUVWXYZ")


@pytest.mark.anyio
async def test_stale_callback_error_is_swallowed():
    dp = _dispatcher("Bad Request: query is too old and response timeout expired or query ID is invalid")
    await dp.feed_update(BOT, _update())  # xato ko'tarilmaydi


@pytest.mark.anyio
async def test_other_bad_request_still_raises():
    dp = _dispatcher("Bad Request: message to edit not found")
    with pytest.raises(TelegramBadRequest):
        await dp.feed_update(BOT, _update())
