#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    from src.config.env import env

    settings_map = {
        "production": "src.config.django.prod",
        "test": "src.config.django.test",
        "development": "src.config.django.base",
    }

    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        settings_map.get(env.DJANGO_ENV, "src.config.django.base"),
    )

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()