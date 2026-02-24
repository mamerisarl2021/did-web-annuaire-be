"""
Session & Cookie configuration.

httpOnly cookies — no JWT in headers.
Sessions stored in Redis cache for performance.
"""

from src.config.env import env

# ── Session engine ──────────────────────────────────────────────────────

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "sessions"

# ── Cookie settings ─────────────────────────────────────────────────────

SESSION_COOKIE_NAME = env.SESSION_COOKIE_NAME
SESSION_COOKIE_AGE = env.SESSION_COOKIE_AGE
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env.SESSION_COOKIE_SECURE
SESSION_COOKIE_SAMESITE = "Lax"

if env.SESSION_COOKIE_DOMAIN:
    SESSION_COOKIE_DOMAIN = env.SESSION_COOKIE_DOMAIN

# ── CSRF ────────────────────────────────────────────────────────────────

CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = env.CSRF_COOKIE_SECURE
CSRF_COOKIE_SAMESITE = "Lax"

# Needed when behind a reverse proxy with HTTPS
if env.is_production:
    CSRF_TRUSTED_ORIGINS = [
        f"https://{host}" for host in env.ALLOWED_HOSTS if host != "*"
    ]

# ── Cache backends (sessions + general) ─────────────────────────────────

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env.CACHE_REDIS_URL,
        "OPTIONS": {
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
        },
    },
    "sessions": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env.SESSION_REDIS_URL,
        "OPTIONS": {
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
        },
    },
}