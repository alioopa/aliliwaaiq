from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BroadcastSegment, BroadcastStatus
from app.db.models import BroadcastJob, ClientBotMember


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_segment(value: str) -> BroadcastSegment:
    normalized = value.strip().upper()
    mapping = {
        "ALL": BroadcastSegment.ALL,
        "ACTIVE_24H": BroadcastSegment.ACTIVE_24H,
        "ACTIVE_7D": BroadcastSegment.ACTIVE_7D,
        "VIP_ONLY": BroadcastSegment.VIP_ONLY,
    }
    if normalized not in mapping:
        raise ValueError("Invalid segment. Use ALL / ACTIVE_24H / ACTIVE_7D / VIP_ONLY.")
    return mapping[normalized]


async def create_broadcast_job(
    session: AsyncSession,
    bot_id: uuid.UUID,
    created_by: int,
    text: str,
    segment: BroadcastSegment,
    scheduled_at: datetime | None = None,
) -> BroadcastJob:
    status = BroadcastStatus.SCHEDULED if scheduled_at else BroadcastStatus.PENDING
    job = BroadcastJob(
        bot_id=bot_id,
        created_by=created_by,
        text=text,
        segment=segment,
        scheduled_at=scheduled_at,
        status=status,
    )
    session.add(job)
    await session.flush()
    return job


async def collect_recipient_ids(
    session: AsyncSession, bot_id: uuid.UUID, segment: BroadcastSegment
) -> list[int]:
    stmt = select(ClientBotMember.telegram_user_id).where(
        and_(
            ClientBotMember.bot_id == bot_id,
            ClientBotMember.is_banned.is_(False),
            ClientBotMember.has_started.is_(True),
        )
    )
    now = utcnow()
    if segment == BroadcastSegment.ACTIVE_24H:
        stmt = stmt.where(ClientBotMember.last_seen_at >= now - timedelta(hours=24))
    elif segment == BroadcastSegment.ACTIVE_7D:
        stmt = stmt.where(ClientBotMember.last_seen_at >= now - timedelta(days=7))
    elif segment == BroadcastSegment.VIP_ONLY:
        stmt = stmt.where(ClientBotMember.is_vip.is_(True))

    result = await session.execute(stmt)
    return list(result.scalars().all())
