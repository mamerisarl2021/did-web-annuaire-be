"""
WSGI entry point for production (gunicorn).

It exposes the WSGI callable as a module-level variable named ``application``.
"""

import os

from src.config.env import env

from django.core.wsgi import get_wsgi_application

_settings_map = {
    "production": "src.config.django.prod",
    "test": "src.config.django.test",
    "development": "src.config.django.base",
}


os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    _settings_map.get(env.DJANGO_ENV, "src.config.django.base"),
)

application = get_wsgi_application()
