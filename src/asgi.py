"""
Configuration ASGI pour le projet.

Il expose l'appelable ASGI en tant que variable de niveau module nommée ``application``.
"""

import os

from src.config.env import env

from django.core.asgi import get_asgi_application

_settings_map = {
    "production": "src.config.django.prod",
    "test": "src.config.django.test",
    "development": "src.config.django.base",
}


os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    _settings_map.get(env.DJANGO_ENV, "src.config.django.base"),
)

application = get_asgi_application()
