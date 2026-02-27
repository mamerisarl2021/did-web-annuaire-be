"""
Celery application.

Imported by celery workers and celery-beat.
The -A flag in compose.yml should point to this: celery -A src.config.celery_app
"""

import os

from celery import Celery
from celery.signals import setup_logging

from src.config.env import env

# Set the Django settings module based on environment
_settings_map = {
    "production": "src.config.django.prod",
    "test": "src.config.django.test",
    "development": "src.config.django.base",
}

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    _settings_map.get(env.DJANGO_ENV, "src.config.django.base"),
)

app = Celery("annuaire_did")

app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py in each app
app.autodiscover_tasks(
    ["src.apps.audits", "src.apps.authentication", "src.apps.files", "src.apps.organizations", "src.apps.emails",
     "src.apps.users", "src.apps.superadmin", "src.seeders", "src.apps.certificates", "src.apps.documents",
     "src.apps.audits", "src"])


@setup_logging.connect
def configure_structlog_for_celery(**kwargs):
    """Prevent Celery from hijacking the root logger. Let structlog handle it."""
    pass
