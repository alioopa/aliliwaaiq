from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PlanType, SubscriptionStatus
from app.db.models import ClientBot, Subscription, SubscriptionReminderLog


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


REMINDER_THRESHOLDS = {
    "7D": 7 * 24 * 3600,
    "3D": 3 * 24 * 3600,
    "24H": 24 * 3600,
    "0D": 0,
}


async def get_due_subscription_reminders(session: AsyncSession) -> list[tuple[Subscription, str]]:
    now = utcnow()
    result = await session.execute(
        select(Subscription).where(
            and_(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at.is_not(None),
                Subscription.expires_at <= now.replace(year=now.year + 1),
            )
        )
    )
    due: list[tuple[Subscription, str]] = []
    for subscription in result.scalars().all():
        if not subscription.expires_at:
            continue
        remaining_seconds = int((subscription.expires_at - now).total_seconds())
        for key, threshold in REMINDER_THRESHOLDS.items():
            if remaining_seconds <= threshold:
                check = await session.execute(
                    select(SubscriptionReminderLog.id).where(
                        and_(
                            SubscriptionReminderLog.subscription_id == subscription.id,
                            SubscriptionReminderLog.reminder_key == key,
                        )
                    )
                )
                if check.scalar_one_or_none() is None:
                    due.append((subscription, key))
                break
    return due


async def mark_reminder_sent(session: AsyncSession, subscription_id, reminder_key: str) -> None:
    session.add(SubscriptionReminderLog(subscription_id=subscription_id, reminder_key=reminder_key))
    await session.flush()


async def expire_due_subscriptions(session: AsyncSession) -> list[Subscription]:
    now = utcnow()
    result = await session.execute(
        select(Subscription).where(
            and_(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at.is_not(None),
                Subscription.expires_at <= now,
            )
        )
    )
    expired: list[Subscription] = []
    for subscription in result.scalars().all():
        subscription.status = SubscriptionStatus.EXPIRED
        subscription.plan_type = PlanType.FREE
        bot = await session.get(ClientBot, subscription.bot_id)
        if bot:
            bot.plan_type = PlanType.FREE
            bot.subscription_expires_at = None
            bot.branding_enabled = True
        expired.append(subscription)
    await session.flush()
    return expired
