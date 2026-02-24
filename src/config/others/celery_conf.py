"""
Celery configuration.

The Celery app instance lives in src/config/celery_app.py (separate from this).
This file only exports Django settings that Celery reads.
"""

from src.config.env import env

CELERY_BROKER_URL = env.CELERY_BROKER_URL
CELERY_RESULT_BACKEND = env.CELERY_RESULT_BACKEND

CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"

CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300  # 5 min hard kill
CELERY_TASK_SOFT_TIME_LIMIT = 240  # 4 min soft warning
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# django-celery-beat
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"