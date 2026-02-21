from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import ForcedChannel


def client_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚙️ لوحة التحكم", callback_data="c:panel"),
                InlineKeyboardButton(text="✅ تحقق الاشتراك", callback_data="c:verify_sub"),
            ]
        ]
    )


def verify_channels_keyboard(channels: list[ForcedChannel]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for channel in channels:
        if channel.channel_username:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"📢 {channel.channel_username}",
                        url=f"https://t.me/{channel.channel_username.lstrip('@')}",
                    )
                ]
            )
    buttons.append([InlineKeyboardButton(text="✅ Verify", callback_data="c:verify_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def owner_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📦 نسخ احتياطي", callback_data="c:backup"),
                InlineKeyboardButton(text="🧩 القوالب", callback_data="c:templates"),
            ],
            [
                InlineKeyboardButton(text="📣 أوامر البث", callback_data="c:broadcast_help"),
                InlineKeyboardButton(text="🛡 الحماية", callback_data="c:security_help"),
            ],
        ]
    )


def templates_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Basic", callback_data="c:template:BASIC"),
                InlineKeyboardButton(text="Community", callback_data="c:template:COMMUNITY"),
                InlineKeyboardButton(text="Store", callback_data="c:template:STORE"),
            ]
        ]
    )

