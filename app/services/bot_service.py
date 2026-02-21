from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from aiogram import Bot
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_token
from app.core.enums import BotStatus, PaymentStatus, PlanType, SubscriptionStatus, UserRole
from app.db.models import (
    BotAd,
    ClientBot,
    ClientBotMember,
    Coupon,
    ForcedChannel,
    PaymentRequest,
    PlatformBan,
    Subscription,
)


PLAN_DURATIONS_DAYS: dict[PlanType, int | None] = {
    PlanType.FREE: None,
    PlanType.MONTHLY: 30,
    PlanType.SEMIANNUAL: 182,
    PlanType.YEARLY: 365,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def validate_bot_token(token: str) -> tuple[str, str | None]:
    bot = Bot(token=token)
    try:
        me = await bot.get_me()
        return me.full_name, me.username
    finally:
        await bot.session.close()


async def create_client_bot(
    session: AsyncSession,
    owner_telegram_id: int,
    token_plain: str,
    bot_name: str,
    bot_username: str | None,
) -> ClientBot:
    token_encrypted = encrypt_token(token_plain)
    client_bot = ClientBot(
        owner_telegram_id=owner_telegram_id,
        name=bot_name,
        username=bot_username,
        token_encrypted=token_encrypted,
        webhook_secret=secrets.token_urlsafe(24),
        status=BotStatus.STOPPED,
        plan_type=PlanType.FREE,
        branding_enabled=True,
    )
    session.add(client_bot)
    await session.flush()

    session.add(
        Subscription(
            bot_id=client_bot.id,
            plan_type=PlanType.FREE,
            status=SubscriptionStatus.ACTIVE,
            starts_at=utcnow(),
            expires_at=None,
        )
    )
    session.add(
        ClientBotMember(
            bot_id=client_bot.id,
            telegram_user_id=owner_telegram_id,
            role=UserRole.OWNER,
            is_vip=True,
            last_seen_at=utcnow(),
        )
    )
    await session.flush()
    return client_bot


async def get_client_bot(session: AsyncSession, bot_id: uuid.UUID) -> ClientBot | None:
    result = await session.execute(select(ClientBot).where(ClientBot.id == bot_id))
    return result.scalar_one_or_none()


async def set_bot_status(session: AsyncSession, bot_id: uuid.UUID, status: BotStatus) -> ClientBot | None:
    bot = await get_client_bot(session, bot_id)
    if not bot:
        return None
    bot.status = status
    if status == BotStatus.RUNNING:
        bot.last_started_at = utcnow()
    else:
        bot.last_stopped_at = utcnow()
    await session.flush()
    return bot


async def list_owner_bots(session: AsyncSession, owner_telegram_id: int) -> list[ClientBot]:
    result = await session.execute(
        select(ClientBot).where(ClientBot.owner_telegram_id == owner_telegram_id).order_by(ClientBot.created_at.desc())
    )
    return list(result.scalars().all())


async def set_subscription_plan(
    session: AsyncSession, bot_id: uuid.UUID, plan_type: PlanType, reset_from_now: bool = True
) -> Subscription:
    result = await session.execute(select(Subscription).where(Subscription.bot_id == bot_id))
    subscription = result.scalar_one_or_none()
    if not subscription:
        subscription = Subscription(
            bot_id=bot_id,
            plan_type=plan_type,
            status=SubscriptionStatus.ACTIVE,
            starts_at=utcnow(),
        )
        session.add(subscription)

    bot = await get_client_bot(session, bot_id)
    if not bot:
        raise ValueError("Client bot not found.")

    base_date = utcnow() if reset_from_now else (subscription.expires_at or utcnow())
    duration = PLAN_DURATIONS_DAYS[plan_type]
    expires_at = None if duration is None else base_date + timedelta(days=duration)

    subscription.plan_type = plan_type
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.starts_at = utcnow()
    subscription.expires_at = expires_at

    bot.plan_type = plan_type
    bot.subscription_expires_at = expires_at
    bot.branding_enabled = plan_type == PlanType.FREE
    await session.flush()
    return subscription


async def upsert_member(
    session: AsyncSession,
    bot: ClientBot,
    telegram_user_id: int,
    increment_interaction: bool = False,
    mark_started: bool = False,
) -> ClientBotMember:
    role = UserRole.OWNER if telegram_user_id == bot.owner_telegram_id else UserRole.USER
    result = await session.execute(
        select(ClientBotMember).where(
            and_(ClientBotMember.bot_id == bot.id, ClientBotMember.telegram_user_id == telegram_user_id)
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        member = ClientBotMember(
            bot_id=bot.id,
            telegram_user_id=telegram_user_id,
            role=role,
            last_seen_at=utcnow(),
            interactions_count=1 if increment_interaction else 0,
            has_started=mark_started,
        )
        session.add(member)
    else:
        member.last_seen_at = utcnow()
        if role == UserRole.OWNER and member.role != UserRole.OWNER:
            member.role = UserRole.OWNER
        if mark_started:
            member.has_started = True
        if increment_interaction:
            member.interactions_count += 1
    await session.flush()
    return member


async def get_user_role(session: AsyncSession, bot: ClientBot, telegram_user_id: int) -> UserRole:
    if telegram_user_id == bot.owner_telegram_id:
        return UserRole.OWNER
    result = await session.execute(
        select(ClientBotMember.role).where(
            and_(ClientBotMember.bot_id == bot.id, ClientBotMember.telegram_user_id == telegram_user_id)
        )
    )
    role = result.scalar_one_or_none()
    return role or UserRole.USER


async def is_platform_banned(session: AsyncSession, telegram_user_id: int) -> bool:
    now = utcnow()
    result = await session.execute(
        select(PlatformBan.id).where(
            and_(
                PlatformBan.telegram_user_id == telegram_user_id,
                (PlatformBan.expires_at.is_(None) | (PlatformBan.expires_at > now)),
            )
        )
    )
    return result.scalar_one_or_none() is not None


async def ban_bot(session: AsyncSession, bot_id: uuid.UUID, reason: str | None) -> ClientBot | None:
    bot = await get_client_bot(session, bot_id)
    if not bot:
        return None
    bot.is_banned = True
    bot.status = BotStatus.STOPPED
    session.add(PlatformBan(bot_id=bot_id, reason=reason))
    await session.flush()
    return bot


async def unban_bot(session: AsyncSession, bot_id: uuid.UUID) -> ClientBot | None:
    bot = await get_client_bot(session, bot_id)
    if not bot:
        return None
    bot.is_banned = False
    await session.flush()
    return bot


async def add_forced_channel(
    session: AsyncSession, bot_id: uuid.UUID, channel_id: int, channel_username: str | None
) -> ForcedChannel:
    result = await session.execute(
        select(ForcedChannel).where(
            and_(ForcedChannel.bot_id == bot_id, ForcedChannel.channel_id == channel_id)
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.channel_username = channel_username
        existing.is_required = True
        await session.flush()
        return existing

    channel = ForcedChannel(
        bot_id=bot_id,
        channel_id=channel_id,
        channel_username=channel_username,
        is_required=True,
    )
    session.add(channel)
    await session.flush()
    return channel


async def list_forced_channels(session: AsyncSession, bot_id: uuid.UUID) -> list[ForcedChannel]:
    result = await session.execute(
        select(ForcedChannel).where(ForcedChannel.bot_id == bot_id).order_by(ForcedChannel.created_at.asc())
    )
    return list(result.scalars().all())


async def remove_forced_channel(session: AsyncSession, bot_id: uuid.UUID, channel_id: int) -> bool:
    result = await session.execute(
        select(ForcedChannel).where(
            and_(ForcedChannel.bot_id == bot_id, ForcedChannel.channel_id == channel_id)
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        return False
    await session.delete(channel)
    return True


async def add_ad(session: AsyncSession, bot_id: uuid.UUID, text: str, every_n_interactions: int) -> BotAd:
    ad = BotAd(bot_id=bot_id, text=text, every_n_interactions=max(every_n_interactions, 1), is_active=True)
    session.add(ad)
    await session.flush()
    return ad


async def get_due_ad(session: AsyncSession, bot_id: uuid.UUID, interactions_count: int) -> BotAd | None:
    result = await session.execute(
        select(BotAd)
        .where(and_(BotAd.bot_id == bot_id, BotAd.is_active.is_(True)))
        .order_by(BotAd.created_at.asc())
    )
    ads = list(result.scalars().all())
    for ad in ads:
        if ad.every_n_interactions > 0 and interactions_count % ad.every_n_interactions == 0:
            return ad
    return None


async def set_bot_setting(session: AsyncSession, bot: ClientBot, key: str, value: Any) -> None:
    payload = dict(bot.settings or {})
    payload[key] = value
    bot.settings = payload
    await session.flush()


async def build_backup_payload(session: AsyncSession, bot: ClientBot) -> dict[str, Any]:
    forced_channels = await list_forced_channels(session, bot.id)
    result = await session.execute(select(BotAd).where(BotAd.bot_id == bot.id).order_by(BotAd.created_at.asc()))
    ads = list(result.scalars().all())
    return {
        "bot_id": str(bot.id),
        "plan_type": bot.plan_type.value,
        "branding_enabled": bot.branding_enabled,
        "ad_frequency": bot.ad_frequency,
        "template_name": bot.template_name,
        "settings": bot.settings or {},
        "forced_channels": [
            {
                "channel_id": item.channel_id,
                "channel_username": item.channel_username,
                "is_required": item.is_required,
            }
            for item in forced_channels
        ],
        "ads": [
            {
                "text": ad.text,
                "is_active": ad.is_active,
                "every_n_interactions": ad.every_n_interactions,
            }
            for ad in ads
        ],
    }


async def restore_backup_payload(session: AsyncSession, bot: ClientBot, payload: dict[str, Any]) -> None:
    bot.settings = payload.get("settings", {})
    bot.ad_frequency = int(payload.get("ad_frequency", bot.ad_frequency))
    bot.template_name = payload.get("template_name")

    channels = await list_forced_channels(session, bot.id)
    for channel in channels:
        await session.delete(channel)

    result_ads = await session.execute(select(BotAd).where(BotAd.bot_id == bot.id))
    for ad in result_ads.scalars().all():
        await session.delete(ad)

    for item in payload.get("forced_channels", []):
        session.add(
            ForcedChannel(
                bot_id=bot.id,
                channel_id=int(item["channel_id"]),
                channel_username=item.get("channel_username"),
                is_required=bool(item.get("is_required", True)),
            )
        )
    for item in payload.get("ads", []):
        session.add(
            BotAd(
                bot_id=bot.id,
                text=item["text"],
                is_active=bool(item.get("is_active", True)),
                every_n_interactions=max(int(item.get("every_n_interactions", 5)), 1),
            )
        )
    await session.flush()


async def create_payment_request(
    session: AsyncSession,
    bot_id: uuid.UUID,
    submitted_by: int,
    amount: Decimal,
    currency: str,
    receipt_url: str | None,
    note: str | None,
) -> PaymentRequest:
    payment = PaymentRequest(
        bot_id=bot_id,
        submitted_by=submitted_by,
        amount=amount,
        currency=currency.upper(),
        receipt_url=receipt_url,
        note=note,
    )
    session.add(payment)
    await session.flush()
    return payment


async def set_payment_status(
    session: AsyncSession,
    payment_id: uuid.UUID,
    status: PaymentStatus,
    reviewed_by: int,
    note: str | None = None,
) -> PaymentRequest | None:
    result = await session.execute(select(PaymentRequest).where(PaymentRequest.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        return None
    payment.status = status
    payment.reviewed_by = reviewed_by
    payment.reviewed_at = utcnow()
    if note:
        payment.note = note
    await session.flush()
    return payment


async def create_coupon(
    session: AsyncSession,
    code: str,
    discount_percent: int,
    max_uses: int,
    expires_at: datetime | None,
    created_by: int,
) -> Coupon:
    coupon = Coupon(
        code=code.upper(),
        discount_percent=max(1, min(discount_percent, 100)),
        max_uses=max(1, max_uses),
        expires_at=expires_at,
        created_by=created_by,
    )
    session.add(coupon)
    await session.flush()
    return coupon


async def redeem_coupon(session: AsyncSession, code: str) -> Coupon | None:
    now = utcnow()
    result = await session.execute(select(Coupon).where(Coupon.code == code.upper()))
    coupon = result.scalar_one_or_none()
    if not coupon:
        return None
    if not coupon.is_active:
        return None
    if coupon.expires_at and coupon.expires_at <= now:
        return None
    if coupon.used_count >= coupon.max_uses:
        return None
    coupon.used_count += 1
    if coupon.used_count >= coupon.max_uses:
        coupon.is_active = False
    await session.flush()
    return coupon


async def get_platform_stats(session: AsyncSession) -> dict[str, int]:
    total_bots = await session.scalar(select(func.count(ClientBot.id)))
    running_bots = await session.scalar(select(func.count(ClientBot.id)).where(ClientBot.status == BotStatus.RUNNING))
    users_total = await session.scalar(select(func.count(ClientBotMember.id)))
    pending_payments = await session.scalar(
        select(func.count(PaymentRequest.id)).where(PaymentRequest.status == PaymentStatus.PENDING)
    )
    return {
        "total_bots": int(total_bots or 0),
        "running_bots": int(running_bots or 0),
        "users_total": int(users_total or 0),
        "pending_payments": int(pending_payments or 0),
    }


def dumps_backup(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
