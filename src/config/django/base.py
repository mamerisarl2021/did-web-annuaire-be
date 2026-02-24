"""
Base Django settings.

Imports split configuration from src/config/others/*.py to keep this file lean.
Production and test settings override specific values from here.
"""

from src.config.env import env, BASE_DIR

# ── Core ────────────────────────────────────────────────────────────────

SECRET_KEY = env.SECRET_KEY
DEBUG = env.DEBUG
ALLOWED_HOSTS = env.ALLOWED_HOSTS

ROOT_URLCONF = "src.urls"
WSGI_APPLICATION = "src.wsgi.application"
ASGI_APPLICATION = "src.asgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
#AUTH_USER_MODEL = "users.User"


# ── Installed Apps ──────────────────────────────────────────────────────

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
    "django_structlog",
    "django_extensions",
]

LOCAL_APPS = []

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ── Middleware ──────────────────────────────────────────────────────────

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
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
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                "django.template.context_processors.debug",
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ── Database ────────────────────────────────────────────────────────────

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




# ── Auth ────────────────────────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]


# ── i18n ────────────────────────────────────────────────────────────────

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ── Split configs (imported from others/) ───────────────────────────────
# Each file exports top-level Django settings variables.

from src.config.others.session import *  # noqa: E402, F401, F403
from src.config.others.cors import *  # noqa: E402, F401, F403
from src.config.others.celery_conf import *  # noqa: E402, F401, F403
from src.config.others.files_and_storages import *  # noqa: E402, F401, F403
from src.config.others.email_sending import *  # noqa: E402, F401, F403
from src.config.others.logging_conf import *  # noqa: E402, F401, F403