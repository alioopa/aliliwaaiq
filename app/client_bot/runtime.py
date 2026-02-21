from __future__ import annotations

from aiogram import Dispatcher

from app.client_bot.handlers import group_router, private_router


def build_client_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(private_router)
    dispatcher.include_router(group_router)
    return dispatcher

