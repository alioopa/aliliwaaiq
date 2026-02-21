from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import PlanType
from app.core.logging import get_logger
from app.db.models import ClientBot
from app.db.session import session_scope
from app.services.subscription_service import (
    expire_due_subscriptions,
    get_due_subscription_reminders,
    mark_reminder_sent,
)
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _reminder_message(key: str, expires_at) -> str:
    labels = {
        "7D": "بعد 7 أيام",
        "3D": "بعد 3 أيام",
        "24H": "بعد 24 ساعة",
        "0D": "اليوم",
    }
    label = labels.get(key, "قريباً")
    return (
        "تنبيه اشتراك:\n"
        f"ينتهي اشتراك البوت {label}.\n"
        f"تاريخ الانتهاء: {expires_at.isoformat()}"
    )


async def _dispatch_due_subscription_reminders() -> dict:
    settings = get_settings()
    if not settings.master_bot_token:
        return {"ok": False, "error": "missing_master_bot_token"}

    bot = Bot(settings.master_bot_token)
    sent_count = 0
    try:
        async with session_scope() as session:
            due = await get_due_subscription_reminders(session)
            for subscription, reminder_key in due:
                client_bot = await session.get(ClientBot, subscription.bot_id)
                if not client_bot:
                    continue
                try:
                    await bot.send_message(
                        client_bot.owner_telegram_id,
                        _reminder_message(reminder_key, subscription.expires_at),
                    )
                    await mark_reminder_sent(session, subscription.id, reminder_key)
                    sent_count += 1
                except Exception:
                    logger.warning(
                        "subscription_reminder_send_failed",
                        bot_id=str(subscription.bot_id),
                        owner_id=client_bot.owner_telegram_id,
                        reminder_key=reminder_key,
                        exc_info=True,
                    )
    finally:
        await bot.session.close()
    return {"ok": True, "sent": sent_count}


@celery_app.task(name="app.tasks.subscriptions.dispatch_due_subscription_reminders")
def dispatch_due_subscription_reminders():
    return asyncio.run(_dispatch_due_subscription_reminders())


async def _expire_subscriptions() -> dict:
    expired_items: list[tuple[str, int]] = []
    settings = get_settings()
    notify_bot = Bot(settings.master_bot_token) if settings.master_bot_token else None
    try:
        async with session_scope() as session:
            expired = await expire_due_subscriptions(session)
            for item in expired:
                client_bot = await session.get(ClientBot, item.bot_id)
                if client_bot:
                    expired_items.append((str(client_bot.id), client_bot.owner_telegram_id))
        if notify_bot:
            for bot_id, owner_telegram_id in expired_items:
                try:
                    await notify_bot.send_message(
                        owner_telegram_id,
                        f"تم انتهاء اشتراك البوت `{bot_id}` والعودة تلقائياً إلى خطة FREE.",
                    )
                except Exception:
                    logger.warning(
                        "subscription_expired_notify_failed",
                        bot_id=bot_id,
                        owner_id=owner_telegram_id,
                        exc_info=True,
                    )
    finally:
        if notify_bot:
            await notify_bot.session.close()
    return {"ok": True, "expired_count": len(expired_items)}


@celery_app.task(name="app.tasks.subscriptions.expire_subscriptions_task")
def expire_subscriptions_task():
    return asyncio.run(_expire_subscriptions())

