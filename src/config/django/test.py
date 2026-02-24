"""
Test settings.

Optimized for speed. Uses SQLite, disables migrations, uses simple hasher.
"""

from src.config.django.base import *  # noqa: F401, F403

# ── Speed ───────────────────────────────────────────────────────────────

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# ── Database (SQLite for fast test runs) ────────────────────────────────

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

# ── Celery (synchronous in tests) ──────────────────────────────────────

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# ── Email ───────────────────────────────────────────────────────────────

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# ── Cache (local memory) ───────────────────────────────────────────────

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    },
}

# ── Sessions (DB-backed in tests since no Redis) ───────────────────────

SESSION_ENGINE = "django.contrib.sessions.backends.db"