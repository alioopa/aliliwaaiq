web: uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT}
worker: celery -A app.tasks.celery_app.celery_app worker -l info --concurrency=2
beat: celery -A app.tasks.celery_app.celery_app beat -l info

