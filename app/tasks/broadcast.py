from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from sqlalchemy import and_, select

from app.core.config import get_settings
from app.core.crypto import decrypt_token
from app.core.enums import BroadcastStatus
from app.core.logging import get_logger
from app.db.models import BroadcastDelivery, BroadcastJob, ClientBot
from app.db.session import session_scope
from app.services.broadcast_service import collect_recipient_ids
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _send_with_retry(bot_api: Bot, user_id: int, text: str) -> tuple[str, str | None, int]:
    settings = get_settings()
    for attempt in range(1, settings.broadcast_max_retries + 1):
        try:
            await bot_api.send_message(user_id, text)
            return "sent", None, attempt
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
        except TelegramForbiddenError as exc:
            return "blocked", str(exc), attempt
        except TelegramBadRequest as exc:
            return "failed", str(exc), attempt
        except TelegramNetworkError as exc:
            await asyncio.sleep(min(2**attempt, 20))
            if attempt == settings.broadcast_max_retries:
                return "failed", str(exc), attempt
        except Exception as exc:
            if attempt == settings.broadcast_max_retries:
                return "failed", str(exc), attempt
            await asyncio.sleep(min(2**attempt, 20))
    return "failed", "unknown_error", settings.broadcast_max_retries


async def _process_broadcast_job(job_id: uuid.UUID) -> dict:
    async with session_scope() as session:
        job = await session.get(BroadcastJob, job_id)
        if not job:
            return {"ok": False, "error": "job_not_found"}
        if job.status in {BroadcastStatus.DONE, BroadcastStatus.PROCESSING}:
            return {"ok": True, "skipped": True}
        bot_model = await session.get(ClientBot, job.bot_id)
        if not bot_model:
            job.status = BroadcastStatus.FAILED
            return {"ok": False, "error": "bot_not_found"}

        recipients = await collect_recipient_ids(session, job.bot_id, job.segment)
        job.total_target = len(recipients)
        job.status = BroadcastStatus.PROCESSING
        job.started_at = utcnow()

    token_plain = decrypt_token(bot_model.token_encrypted)
    bot_api = Bot(token=token_plain)
    settings = get_settings()

    sent_count = 0
    failed_count = 0
    blocked_count = 0
    deliveries: list[BroadcastDelivery] = []

    try:
        for user_id in recipients:
            status, error, attempts = await _send_with_retry(bot_api, user_id, job.text)
            if status == "sent":
                sent_count += 1
            elif status == "blocked":
                blocked_count += 1
            else:
                failed_count += 1

            deliveries.append(
                BroadcastDelivery(
                    job_id=job.id,
                    bot_id=job.bot_id,
                    telegram_user_id=user_id,
                    status=status,
                    attempts=attempts,
                    error=error,
                    sent_at=utcnow() if status == "sent" else None,
                )
            )
            await asyncio.sleep(settings.broadcast_flood_sleep)
    finally:
        await bot_api.session.close()

    async with session_scope() as session:
        db_job = await session.get(BroadcastJob, job_id)
        if not db_job:
            return {"ok": False, "error": "job_deleted"}
        db_job.sent_count = sent_count
        db_job.failed_count = failed_count
        db_job.blocked_count = blocked_count
        db_job.finished_at = utcnow()
        db_job.status = BroadcastStatus.DONE if (sent_count + blocked_count + failed_count) > 0 else BroadcastStatus.FAILED
        for delivery in deliveries:
            session.add(delivery)
        owner_id = None
        bot_ref = await session.get(ClientBot, db_job.bot_id)
        if bot_ref:
            owner_id = bot_ref.owner_telegram_id

    if owner_id:
        token_plain = decrypt_token(bot_model.token_encrypted)
        report_bot = Bot(token_plain)
        try:
            await report_bot.send_message(
                owner_id,
                "تقرير البث:\n"
                f"- Job: `{job_id}`\n"
                f"- المستهدف: {len(recipients)}\n"
                f"- تم الإرسال: {sent_count}\n"
                f"- محظور: {blocked_count}\n"
                f"- فشل: {failed_count}",
            )
        except Exception:
            logger.warning("broadcast_report_send_failed", job_id=str(job_id), owner_id=owner_id, exc_info=True)
        finally:
            await report_bot.session.close()

    return {
        "ok": True,
        "job_id": str(job_id),
        "sent": sent_count,
        "blocked": blocked_count,
        "failed": failed_count,
    }


@celery_app.task(name="app.tasks.broadcast.process_broadcast_job", bind=True)
def process_broadcast_job(self, job_id: str):
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError:
        return {"ok": False, "error": "invalid_job_id"}
    return asyncio.run(_process_broadcast_job(parsed_id))


async def _dispatch_due_broadcasts() -> int:
    now = utcnow()
    dispatched = 0
    async with session_scope() as session:
        result = await session.execute(
            select(BroadcastJob).where(
                and_(
                    BroadcastJob.status == BroadcastStatus.SCHEDULED,
                    BroadcastJob.scheduled_at.is_not(None),
                    BroadcastJob.scheduled_at <= now,
                )
            )
        )
        jobs = list(result.scalars().all())
        for job in jobs:
            job.status = BroadcastStatus.PENDING
            celery_app.send_task("app.tasks.broadcast.process_broadcast_job", args=[str(job.id)])
            dispatched += 1
    return dispatched


@celery_app.task(name="app.tasks.broadcast.dispatch_due_broadcasts")
def dispatch_due_broadcasts():
    return asyncio.run(_dispatch_due_broadcasts())
