from __future__ import annotations

import asyncio
from contextlib import suppress
import uuid
from dataclasses import dataclass

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update
from celery import Celery
from redis.asyncio import Redis
from sqlalchemy import and_, select

from app.client_bot.runtime import build_client_dispatcher
from app.core.config import Settings
from app.core.crypto import decrypt_token
from app.core.enums import BotStatus
from app.core.logging import get_logger
from app.db.models import ClientBot
from app.db.session import session_scope

logger = get_logger(__name__)


@dataclass
class ClientRuntime:
    bot_id: uuid.UUID
    webhook_secret: str
    bot: Bot
    dispatcher: object
    polling_task: asyncio.Task | None = None


class BotManager:
    def __init__(self, settings: Settings, celery_app: Celery, redis_client: Redis) -> None:
        self.settings = settings
        self.celery_app = celery_app
        self.redis_client = redis_client
        self._runtimes: dict[uuid.UUID, ClientRuntime] = {}
        self._lock = asyncio.Lock()

    async def start_existing_bots(self) -> None:
        async with session_scope() as session:
            result = await session.execute(
                select(ClientBot).where(
                    and_(ClientBot.status == BotStatus.RUNNING, ClientBot.is_banned.is_(False))
                )
            )
            bots = list(result.scalars().all())
        for bot in bots:
            try:
                await self._start_runtime(bot)
            except Exception:
                logger.exception("start_existing_bot_failed", bot_id=str(bot.id))

    async def _start_runtime(self, model: ClientBot) -> ClientRuntime:
        token = decrypt_token(model.token_encrypted)
        bot_api = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dispatcher = build_client_dispatcher()
        runtime = ClientRuntime(
            bot_id=model.id,
            webhook_secret=model.webhook_secret,
            bot=bot_api,
            dispatcher=dispatcher,
        )
        self._runtimes[model.id] = runtime

        if self.settings.webhook_base_url:
            webhook_url = f"{self.settings.webhook_base_url}/webhook/client/{model.id}/{model.webhook_secret}"
            await bot_api.set_webhook(webhook_url, drop_pending_updates=False)
            logger.info("client_webhook_set", bot_id=str(model.id), url=webhook_url)
        else:
            runtime.polling_task = asyncio.create_task(
                dispatcher.start_polling(
                    bot_api,
                    tenant_bot_id=model.id,
                    celery_app=self.celery_app,
                    redis_client=self.redis_client,
                    handle_signals=False,
                ),
                name=f"client_bot_polling_{model.id}",
            )
            logger.info("client_polling_started", bot_id=str(model.id))
        return runtime

    async def start_bot(self, bot_id: uuid.UUID) -> None:
        async with self._lock:
            if bot_id in self._runtimes:
                return
            async with session_scope() as session:
                model = await session.get(ClientBot, bot_id)
                if not model:
                    raise ValueError("Bot not found.")
                if model.is_banned:
                    raise ValueError("Bot is banned.")
                model.status = BotStatus.RUNNING
                await session.flush()
            await self._start_runtime(model)

    async def stop_bot(self, bot_id: uuid.UUID) -> None:
        async with self._lock:
            runtime = self._runtimes.pop(bot_id, None)
            if runtime:
                if self.settings.webhook_base_url:
                    try:
                        await runtime.bot.delete_webhook(drop_pending_updates=False)
                    except Exception:
                        logger.warning("delete_webhook_failed", bot_id=str(bot_id), exc_info=True)
                if runtime.polling_task:
                    runtime.polling_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await runtime.polling_task
                await runtime.bot.session.close()

            async with session_scope() as session:
                model = await session.get(ClientBot, bot_id)
                if model:
                    model.status = BotStatus.STOPPED
                    await session.flush()

    async def restart_bot(self, bot_id: uuid.UUID) -> None:
        await self.stop_bot(bot_id)
        await self.start_bot(bot_id)

    async def dispatch_update(self, bot_id: uuid.UUID, secret: str, payload: dict) -> bool:
        runtime = self._runtimes.get(bot_id)
        if not runtime:
            return False
        if secret != runtime.webhook_secret:
            return False
        update = Update.model_validate(payload)
        await runtime.dispatcher.feed_update(
            runtime.bot,
            update,
            tenant_bot_id=bot_id,
            celery_app=self.celery_app,
            redis_client=self.redis_client,
        )
        return True

    async def shutdown(self) -> None:
        for bot_id in list(self._runtimes.keys()):
            try:
                await self.stop_bot(bot_id)
            except Exception:
                logger.exception("shutdown_bot_failed", bot_id=str(bot_id))
