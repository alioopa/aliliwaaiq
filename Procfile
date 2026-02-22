web: python -m app.run
worker: celery -A app.tasks.celery_app.celery_app worker -l info --concurrency=2
beat: celery -A app.tasks.celery_app.celery_app beat -l info
