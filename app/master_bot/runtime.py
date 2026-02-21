from __future__ import annotations

import asyncio
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

from app.bot_manager.manager import BotManager
from app.core.config import Settings
from app.core.logging import get_logger
from app.master_bot.handlers import router as master_router

logger = get_logger(__name__)


class MasterBotRuntime:
    def __init__(self, settings: Settings, bot_manager: BotManager) -> None:
        self.settings = settings
        self.bot_manager = bot_manager
        self._polling_task: asyncio.Task | None = None
        self.bot = Bot(
            token=settings.master_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dispatcher = Dispatcher()
        self.dispatcher.include_router(master_router)

    async def start(self) -> None:
        if self.settings.webhook_base_url:
            webhook_url = f"{self.settings.webhook_base_url}/webhook/master/{self.settings.master_bot_webhook_secret}"
            await self.bot.set_webhook(webhook_url, drop_pending_updates=False)
            logger.info("master_webhook_set", url=webhook_url)
            return

        logger.warning("master_webhook_skipped", reason="WEBHOOK_BASE_URL is empty, polling mode enabled")
        self._polling_task = asyncio.create_task(
            self.dispatcher.start_polling(
                self.bot,
                bot_manager=self.bot_manager,
                handle_signals=False,
            ),
            name="master_bot_polling",
        )
        logger.info("master_polling_started")

    async def dispatch_update(self, payload: dict) -> None:
        update = Update.model_validate(payload)
        await self.dispatcher.feed_update(self.bot, update, bot_manager=self.bot_manager)

    async def shutdown(self) -> None:
        if self.settings.webhook_base_url:
            try:
                await self.bot.delete_webhook(drop_pending_updates=False)
            except Exception:
                logger.warning("master_delete_webhook_failed", exc_info=True)
        if self._polling_task:
            self._polling_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._polling_task
        await self.bot.session.close()
