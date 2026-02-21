from __future__ import annotations

import random
import re
import uuid
from datetime import timedelta, timezone

from aiogram import F, Router
from aiogram.types import ChatPermissions, Message
from redis.asyncio import Redis

from app.core.enums import UserRole
from app.db.session import session_scope
from app.services.bot_service import get_client_bot, get_user_role, upsert_member

router = Router(name="client_group")

LINK_RE = re.compile(r"(https?://|t\.me/|@\w+)", re.IGNORECASE)


async def _warn_mute_kick(message: Message, warnings_count: int, max_warns: int) -> None:
    if warnings_count >= max_warns:
        await message.bot.ban_chat_member(message.chat.id, message.from_user.id)
        await message.reply("تم طرد المستخدم بعد تجاوز الحد المسموح من التحذيرات.")
        return

    if warnings_count == max_warns - 1:
        until = message.date.replace(tzinfo=timezone.utc) + timedelta(hours=1)
        await message.bot.restrict_chat_member(
            message.chat.id,
            message.from_user.id,
            ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        await message.reply("تم كتم المستخدم لمدة ساعة.")
        return

    await message.reply(f"تحذير ({warnings_count}/{max_warns})")


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def moderation_handler(message: Message, tenant_bot_id: uuid.UUID, redis_client: Redis) -> None:
    if not message.from_user or message.from_user.is_bot:
        return

    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return

        config = bot.settings or {}
        anti_link = bool(config.get("anti_link", True))
        anti_spam = bool(config.get("anti_spam", True))
        captcha_enabled = bool(config.get("captcha_enabled", False))
        forbidden_words = [w.lower() for w in config.get("forbidden_words", [])]
        max_warns = max(2, int(config.get("max_warns", 3)))

        if captcha_enabled and message.new_chat_members:
            for newcomer in message.new_chat_members:
                if newcomer.is_bot:
                    continue
                code = str(random.randint(1000, 9999))
                key = f"captcha:{tenant_bot_id}:{message.chat.id}:{newcomer.id}"
                await redis_client.set(key, code, ex=300)
                await message.bot.restrict_chat_member(
                    message.chat.id,
                    newcomer.id,
                    ChatPermissions(can_send_messages=False),
                    until_date=message.date.replace(tzinfo=timezone.utc) + timedelta(minutes=5),
                )
                await message.answer(
                    f"مرحباً {newcomer.full_name}.\n"
                    f"Captcha: اكتب الرقم `{code}` في المجموعة خلال 5 دقائق لتفعيل الكتابة."
                )
            return

        text = (message.text or message.caption or "").lower().strip()
        if not text:
            return

        member = await upsert_member(session, bot, message.from_user.id, increment_interaction=False)
        role = await get_user_role(session, bot, message.from_user.id)
        if role in {UserRole.OWNER, UserRole.ADMIN, UserRole.MOD}:
            return

        if captcha_enabled:
            captcha_key = f"captcha:{tenant_bot_id}:{message.chat.id}:{message.from_user.id}"
            expected = await redis_client.get(captcha_key)
            if expected:
                if text == expected:
                    await message.bot.restrict_chat_member(
                        message.chat.id,
                        message.from_user.id,
                        ChatPermissions(can_send_messages=True),
                    )
                    await redis_client.delete(captcha_key)
                    await message.reply("تم التحقق من Captcha ✅")
                else:
                    await message.reply("رمز Captcha غير صحيح.")
                return

        violated = False
        if anti_link and LINK_RE.search(text):
            violated = True

        if not violated and forbidden_words:
            if any(word in text for word in forbidden_words):
                violated = True

        if not violated and anti_spam:
            key = f"spam:{tenant_bot_id}:{message.chat.id}:{message.from_user.id}"
            count = await redis_client.incr(key)
            if count == 1:
                await redis_client.expire(key, 12)
            if count >= 6:
                violated = True

        if violated:
            member.warnings_count += 1
            await _warn_mute_kick(message, member.warnings_count, max_warns)
