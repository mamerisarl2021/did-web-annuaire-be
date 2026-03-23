"""
Paramètres de production.

N'écrase que les valeurs qui DOIVENT différer de base.py.
Importé via DJANGO_SETTINGS_MODULE=src.config.django.prod
"""

from src.config.django.base import *  # noqa: F401, F403
from src.config.env import env

# ── Sécurité ────────────────────────────────────────────────────────────

DEBUG = env.DEBUG

ALLOWED_HOSTS = env.ALLOWED_HOSTS

SECURE_SSL_REDIRECT = False  # Géré par nginx / proxy inverse
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# ── Cookies (plus stricts en production) ────────────────────────────────

SESSION_COOKIE_SECURE = True
# SESSION_COOKIE_DOMAIN = env.SESSION_COOKIE_DOMAIN or None
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS: list[str] = [
    f"https://{host}" for host in env.ALLOWED_HOSTS if host != "*"
]

# ── Base de données ─────────────────────────────────────────────────────

DATABASES["default"]["CONN_MAX_AGE"] = 600  # noqa: F405

# ── Surcharge de journalisation ─────────────────────────────────────────
# En production, structlog rend du JSON (configuré dans logging_conf.py
# basé sur env.is_production). Aucune surcharge nécessaire ici — c'est automatique.

# ── E-mail ──────────────────────────────────────────────────────────────

EMAIL_BACKEND = env.EMAIL_BACKEND

# ── Autres ──────────────────────────────────────────────────────────────
JWK_EXTRACTOR_JAR = "/app/bin/ecdsa-extractor.jar"
JWK_EXTRACTOR_JAVA = "java"
