"""
Production settings.

Only overrides values that MUST differ from base.py.
Imported via DJANGO_SETTINGS_MODULE=src.config.django.prod
"""

from src.config.django.base import *  # noqa: F401, F403
from src.config.env import env

# ── Security ────────────────────────────────────────────────────────────

DEBUG = False

ALLOWED_HOSTS = env.ALLOWED_HOSTS

SECURE_SSL_REDIRECT = False  # Handled by nginx / reverse proxy
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# ── Cookies (stricter in production) ────────────────────────────────────

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_DOMAIN = env.SESSION_COOKIE_DOMAIN or None
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = [
    f"https://{host}" for host in env.ALLOWED_HOSTS if host != "*"
]

# ── Database ────────────────────────────────────────────────────────────

DATABASES["default"]["CONN_MAX_AGE"] = 600  # noqa: F405

# ── Logging override ───────────────────────────────────────────────────
# In production, structlog renders JSON (configured in logging_conf.py
# based on env.is_production). No override needed here — it's automatic.

# ── Email ───────────────────────────────────────────────────────────────

EMAIL_BACKEND = env.EMAIL_BACKEND

# ── Others ───────────────────────────────────────────────────
JWK_EXTRACTOR_JAR = "/app/bin/ecdsa-extractor.jar"
JWK_EXTRACTOR_JAVA = "java"