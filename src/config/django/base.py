"""
Paramètres de base de Django.

Importe la configuration scindée depuis src/config/others/*.py pour alléger ce fichier.
Les paramètres de production et de test écrasent des valeurs spécifiques d'ici.
"""

import os

from src.config.env import BASE_DIR, env

# ── Cœur ────────────────────────────────────────────────────────────────

SECRET_KEY = env.SECRET_KEY
DEBUG = env.DEBUG
ALLOWED_HOSTS = env.ALLOWED_HOSTS

ROOT_URLCONF = "src.urls"
WSGI_APPLICATION = "src.wsgi.application"
ASGI_APPLICATION = "src.asgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "users.User"

CSRF_TRUSTED_ORIGINS = env.CSRF_TRUSTED_ORIGINS

# ── Autres ──────────────────────────────────────────────────────────────

PLATFORM_DOMAIN = env.PLATFORM_DOMAIN
CSRF_COOKIE_SECURE = env.CSRF_COOKIE_SECURE
_DOMAIN = "localhost"

# ── Services Externes ───────────────────────────────────────────────────

UNIVERSAL_REGISTRAR_URL = env.UNIVERSAL_REGISTRAR_URL
UNIVERSAL_RESOLVER_URL = env.UNIVERSAL_RESOLVER_URL
SIGNSERVER_URL = env.SIGNSERVER_URL
SIGNSERVER_WORKER_NAME = env.SIGNSERVER_WORKER_NAME
JWK_EXTRACTOR_JAR = env.JWK_EXTRACTOR_JAR
PLATFORM_DOMAIN_WITHOUT_SCHEME = env.PLATFORM_DOMAIN_WITHOUT_SCHEME

# ── Applications Installées ─────────────────────────────────────────────

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "corsheaders",
    "django_celery_beat",
    "django_celery_results",
    "django_structlog",
    "django_extensions",
    "ninja_extra",
    "ninja_jwt",
    "ninja_jwt.token_blacklist",
    "django_htmx",
    "whitenoise.runserver_nostatic",
]

LOCAL_APPS = [
    "src.apps.organizations",
    "src.apps.authentication",
    "src.apps.users",
    "src.apps.files",
    "src.apps.emails",
    "src.apps.superadmin",
    "src.apps.orgadmin",
    "src.apps.certificates",
    "src.apps.documents",
    "src.apps.audits",
    "src.bootstrap",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ── Intergiciels (Middleware) ───────────────────────────────────────────

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "src.common.middleware.RequestContextMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_structlog.middlewares.RequestMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ── Base de Données ─────────────────────────────────────────────────────

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env.POSTGRES_DB,
        "USER": env.POSTGRES_USER,
        "PASSWORD": env.POSTGRES_PASSWORD,
        "HOST": env.POSTGRES_HOST,
        "PORT": env.POSTGRES_PORT,
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "connect_timeout": 10,
        },
        "ATOMIC_REQUESTS": True,
    },
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env.CACHE_REDIS_URL,
        "OPTIONS": {
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
        },
    },
}

# ── Authentification ────────────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# ── Internationalisation (i18n) ─────────────────────────────────────────

LANGUAGE_CODE = "en-us"
# LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ADMIN_USER_NAME = "david"
# ADMIN_USER_EMAIL = "princedavealex.20@gmail.com"

# ADMINS = []

# if ADMIN_USER_NAME and ADMIN_USER_EMAIL:
#    ADMINS.append((ADMIN_USER_NAME, ADMIN_USER_EMAIL))

# MANAGERS = ADMINS

# ── Configurations scindées (importées depuis others/) ──────────────────
# Chaque fichier exporte des variables de paramètres Django de haut niveau.

from src.config.others.celery_conf import *  # noqa: E402, F401, F403

# from src.config.others.session import *  # noqa: E402, F401, F403
from src.config.others.cors import *  # noqa: E402, F401, F403
from src.config.others.email_sending import *  # noqa: E402, F401, F403
from src.config.others.files_and_storages import *  # noqa: E402, F401, F403
from src.config.others.jwt import *  # noqa: E402, F401, F403
from src.config.others.logging_conf import *  # noqa: E402, F401, F403
