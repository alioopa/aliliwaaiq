from aiogram.fsm.state import State, StatesGroup


class MasterStates(StatesGroup):
    waiting_bot_token = State()

