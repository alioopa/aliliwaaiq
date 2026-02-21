from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def master_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ إضافة بوت عميل", callback_data="m:newbot"),
                InlineKeyboardButton(text="🤖 بوتاتي", callback_data="m:mybots"),
            ],
            [
                InlineKeyboardButton(text="📊 إحصائيات", callback_data="m:stats"),
                InlineKeyboardButton(text="📘 أوامر", callback_data="m:help"),
            ],
        ]
    )

