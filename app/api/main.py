from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from aiogram import Bot
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import and_, func, select

from app.bot_manager.manager import BotManager
from app.core.config import get_settings
from app.core.crypto import decrypt_token
from app.core.enums import BotStatus
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, get_redis
from app.db.models import ClientBot
from app.db.base import Base
from app.db.session import get_engine
from app.db.session import session_scope
from app.master_bot.runtime import MasterBotRuntime
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    settings.validate_runtime()
    redis_client = get_redis()

    if settings.database_url.startswith("sqlite+"):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("sqlite_schema_ready")

    bot_manager = BotManager(settings=settings, celery_app=celery_app, redis_client=redis_client)
    master_runtime = MasterBotRuntime(settings=settings, bot_manager=bot_manager)

    app.state.settings = settings
    app.state.bot_manager = bot_manager
    app.state.master_runtime = master_runtime

    await bot_manager.start_existing_bots()
    await master_runtime.start()
    logger.info("app_started", app_name=settings.app_name, environment=settings.environment)
    try:
        yield
    finally:
        await master_runtime.shutdown()
        await bot_manager.shutdown()
        await close_redis()
        logger.info("app_stopped")


app = FastAPI(title="Telegram Bot Maker Platform", lifespan=lifespan)


@app.get("/health")
async def health():
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.get("/")
async def root():
    return {"service": "telegram-bot-maker", "status": "running"}


@app.post("/webhook/master/{secret}")
async def master_webhook(secret: str, request: Request):
    settings = request.app.state.settings
    if secret != settings.master_bot_webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    payload = await request.json()
    await request.app.state.master_runtime.dispatch_update(payload)
    return {"ok": True}


@app.post("/webhook/client/{bot_id}/{secret}")
async def client_webhook(bot_id: str, secret: str, request: Request):
    try:
        parsed_id = uuid.UUID(bot_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid bot_id")
    payload = await request.json()
    dispatched = await request.app.state.bot_manager.dispatch_update(parsed_id, secret, payload)
    if not dispatched:
        raise HTTPException(status_code=404, detail="Runtime not found or secret mismatch")
    return {"ok": True}


def _require_ops_auth(request: Request) -> None:
    ops_key = request.app.state.settings.ops_api_key
    if not ops_key:
        raise HTTPException(status_code=403, detail="OPS_API_KEY is not configured")
    if request.headers.get("x-ops-key") != ops_key:
        raise HTTPException(status_code=401, detail="Invalid ops key")


@app.get("/ops/status")
async def ops_status(request: Request):
    _require_ops_auth(request)
    settings = request.app.state.settings
    result: dict = {
        "webhook_base_url": settings.webhook_base_url or "",
        "master_admin_ids_count": len(settings.admin_id_set),
    }
    bot = Bot(settings.master_bot_token)
    try:
        info = await bot.get_webhook_info()
        result["master_webhook"] = {
            "url": info.url,
            "pending_update_count": info.pending_update_count,
            "last_error_message": info.last_error_message,
            "last_error_date": str(info.last_error_date) if info.last_error_date else None,
        }
    finally:
        await bot.session.close()

    async with session_scope() as session:
        running_count = await session.scalar(
            select(func.count(ClientBot.id)).where(
                and_(ClientBot.status == BotStatus.RUNNING, ClientBot.is_banned.is_(False))
            )
        )
    result["running_client_bots"] = int(running_count or 0)
    return result


@app.post("/ops/sync-master-webhook")
async def sync_master_webhook(request: Request):
    _require_ops_auth(request)
    settings = request.app.state.settings
    if not settings.webhook_base_url:
        raise HTTPException(status_code=400, detail="WEBHOOK_BASE_URL is empty")
    webhook_url = f"{settings.webhook_base_url}/webhook/master/{settings.master_bot_webhook_secret}"
    bot = Bot(settings.master_bot_token)
    try:
        await bot.set_webhook(webhook_url, drop_pending_updates=False)
        info = await bot.get_webhook_info()
        return {"ok": True, "url": info.url, "pending_update_count": info.pending_update_count}
    finally:
        await bot.session.close()


@app.post("/ops/sync-client-webhooks")
async def sync_client_webhooks(request: Request):
    _require_ops_auth(request)
    settings = request.app.state.settings
    if not settings.webhook_base_url:
        raise HTTPException(status_code=400, detail="WEBHOOK_BASE_URL is empty")
    synced = 0
    failed: list[str] = []
    async with session_scope() as session:
        result = await session.execute(
            select(ClientBot).where(and_(ClientBot.status == BotStatus.RUNNING, ClientBot.is_banned.is_(False)))
        )
        items = list(result.scalars().all())
    for item in items:
        webhook_url = f"{settings.webhook_base_url}/webhook/client/{item.id}/{item.webhook_secret}"
        try:
            token_plain = decrypt_token(item.token_encrypted)
            bot_api = Bot(token_plain)
            try:
                await bot_api.set_webhook(webhook_url, drop_pending_updates=False)
            finally:
                await bot_api.session.close()
            synced += 1
        except Exception:
            failed.append(str(item.id))
            logger.warning("client_webhook_sync_failed", bot_id=str(item.id), exc_info=True)
    return {"ok": True, "synced": synced, "failed": failed}
