from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.bot_manager.manager import BotManager
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, get_redis
from app.db.base import Base
from app.db.session import get_engine
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
