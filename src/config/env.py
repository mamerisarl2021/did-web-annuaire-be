"""
Environment configuration via pydantic_settings.

This is the SINGLE SOURCE OF TRUTH for all environment variables.
Django settings files import from here — they never read os.environ directly.

Usage:
    from src.config.env import env
    env.SECRET_KEY
    env.DATABASE_URL

Environment switching:
    - DJANGO_ENV is read ONCE here to determine the environment.
    - DJANGO_SETTINGS_MODULE is set accordingly in manage.py / wsgi.py / asgi.py.
    - The .env file is loaded automatically (defaults to .env.backend).
"""

from pathlib import Path
from urllib.parse import quote

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root (above src/)


class AppSettings(BaseSettings):
    """
    All environment variables in one place.
    Fields have sensible dev defaults; production overrides via .env.backend.
    """

    model_config = SettingsConfigDict(
        env_file=".env.backend",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore env vars not declared here
        case_sensitive=False,
    )

    # ── Environment switch ──────────────────────────────────────────────
    # "development" | "production" | "test"
    DJANGO_ENV: str = Field(default="development")

    # ── Django core ─────────────────────────────────────────────────────
    SECRET_KEY: str = "insecure-dev-key-change-in-production"
    DEBUG: bool = True
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1"]

    # ── Database ────────────────────────────────────────────────────────
    POSTGRES_USER: str = "annuaire"
    POSTGRES_PASSWORD: str = "changeme_postgres"
    POSTGRES_DB: str = "annuaire_did"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── Redis ───────────────────────────────────────────────────────────
    #REDIS_PASSWORD: str = "changeme_redis"
    REDIS_PASSWORD: str = "redisallow-alex@123"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    @property
    def REDIS_URL(self) -> str:
        password = quote(self.REDIS_PASSWORD)
        return f"redis://:{password}@{self.REDIS_HOST}:{self.REDIS_PORT}"

    @property
    def CELERY_BROKER_URL(self) -> str:
        return f"{self.REDIS_URL}/0"

    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        return 'django-db'
        #return f"{self.REDIS_URL}/1"

    @property
    def CACHE_REDIS_URL(self) -> str:
        return f"{self.REDIS_URL}/2"

    #@property
    #def SESSION_REDIS_URL(self) -> str:
    #    return f"{self.REDIS_URL}/3"

    # ── Session / Cookies ───────────────────────────────────────────────
    # SESSION_COOKIE_NAME: str = "annuaire_session"
    # SESSION_COOKIE_AGE: int = 86400  # 24h
    # SESSION_COOKIE_SECURE: bool = False
    # SESSION_COOKIE_DOMAIN: str = ""
    # CSRF_COOKIE_SECURE: bool = False

    # ── JWT ─────────────────────────────────────────────────────────────

    JWT_ACCESS_TOKEN_LIFETIME_MINUTES: int = 30
    JWT_REFRESH_TOKEN_LIFETIME_DAYS: int = 7
    JWT_SIGNING_KEY: str = ""

    @property
    def jwt_signing_key(self) -> str:
        return self.JWT_SIGNING_KEY or self.SECRET_KEY

    # ── External services ───────────────────────────────────────────────
    UNIVERSAL_REGISTRAR_URL: str = ""
    SIGNSERVER_URL: str = ""
    SIGNSERVER_WORKER_NAME: str = ""
    JWK_EXTRACTOR_JAR: str = "/home/davieddee/WORKSPACE/did-web-annuaire-be/artifacts/ecdsa-extractor.jar"

    # ── Platform ────────────────────────────────────────────────────────
    PLATFORM_DOMAIN: str = "localhost:8000"
    SUPERADMIN_EMAIL: str = ""
    SUPERADMIN_PASSWORD: str = ""
    SUPERADMIN_FULL_NAME: str = ""

    @property
    def PLATFORM_DID(self) -> str:
        return f"did:web:{self.PLATFORM_DOMAIN}"

    # ── Email ───────────────────────────────────────────────────────────
    EMAIL_BACKEND: str = "django.core.mail.backends.console.EmailBackend"
    EMAIL_HOST: str = "smtp.example.com"
    EMAIL_PORT: int = 587
    EMAIL_HOST_USER: str = ""
    EMAIL_HOST_PASSWORD: str = ""
    EMAIL_USE_TLS: bool = True
    DEFAULT_FROM_EMAIL: str = "noreply@qcdigitalhub.com"

    # ── CORS ────────────────────────────────────────────────────────────
    CORS_ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    # ── Gunicorn ────────────────────────────────────────────────────────
    GUNICORN_WORKERS: int = 4
    GUNICORN_BIND: str = "0.0.0.0:8899"

    @field_validator("DJANGO_ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "production", "test"}
        if v not in allowed:
            msg = f"DJANGO_ENV must be one of {allowed}, got '{v}'"
            raise ValueError(msg)
        return v

    @property
    def is_production(self) -> bool:
        return self.DJANGO_ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.DJANGO_ENV == "development"

    @property
    def is_test(self) -> bool:
        return self.DJANGO_ENV == "test"


# ── Singleton ───────────────────────────────────────────────────────────
# Instantiated once at import time. All Django settings files use this.
env = AppSettings()