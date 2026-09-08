from aiogram.filters.callback_data import CallbackData


class AdminMenuCallback(CallbackData, prefix="admin"):
    action: str


class QuestionCallback(CallbackData, prefix="question"):
    action: str
    question_id: int | None = None


class ResetCallback(CallbackData, prefix="reset"):
    confirm: bool


class UserListCallback(CallbackData, prefix="users"):
    action: str
    user_id: int | None = None