from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    waiting_full_name = State()  # ✅ waiting_name → waiting_full_name
    waiting_phone = State()


class AdminQuestionsStates(StatesGroup):
    menu = State()
    waiting_docx = State()
    waiting_docx_ai = State()
    confirm_delete = State()


class AdminActivateStates(StatesGroup):
    confirm = State()


class AdminResultsStates(StatesGroup):
    menu = State()
    search_user = State()
    unblock_user = State()


class AdminTestAccessStates(StatesGroup):
    menu = State()
    waiting_vip_limit = State()


class TestStates(StatesGroup):
    in_progress = State()
    answering = State()
    finished = State()