from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "telegram_platform",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
    include=[
        "app.tasks.broadcast",
        "app.tasks.subscriptions",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.default_timezone,
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    beat_schedule={
        "dispatch-due-broadcasts-every-minute": {
            "task": "app.tasks.broadcast.dispatch_due_broadcasts",
            "schedule": crontab(minute="*"),
        },
        "dispatch-subscription-reminders-every-30-min": {
            "task": "app.tasks.subscriptions.dispatch_due_subscription_reminders",
            "schedule": crontab(minute="*/30"),
        },
        "expire-subscriptions-hourly": {
            "task": "app.tasks.subscriptions.expire_subscriptions_task",
            "schedule": crontab(minute="15"),
        },
    },
)

