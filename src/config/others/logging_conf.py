"""
Logging configuration with structlog + django-structlog.

Development: colored, human-readable console output.
Production:  JSON lines (one JSON object per log line — ready for log aggregators).

The switch is automatic based on DJANGO_ENV.
"""

import structlog

from src.config.env import env


# ── structlog shared processors ─────────────────────────────────────────
# These run for every log event regardless of environment.

shared_processors: list[structlog.types.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.filter_by_level,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.stdlib.PositionalArgumentsFormatter(),
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.UnicodeDecoder(),
]

# ── Environment-specific renderer ───────────────────────────────────────

if env.is_production:
    # JSON renderer for production (one JSON object per line)
    renderer = structlog.processors.JSONRenderer()
else:
    # Colored, human-readable output for development
    renderer = structlog.dev.ConsoleRenderer(colors=True)


# ── structlog configuration ─────────────────────────────────────────────

structlog.configure(
    processors=[
        *shared_processors,
        # Prepare for stdlib logging integration
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)


# ── Django LOGGING dict ─────────────────────────────────────────────────
# Routes Django's stdlib logging through structlog's ProcessorFormatter.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structlog": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processors": [
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structlog",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",  # Suppress SQL noise unless debugging
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "celery": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "src": {
            "handlers": ["console"],
            "level": "DEBUG" if env.is_development else "INFO",
            "propagate": False,
        },
    },
}

# ── django-structlog ────────────────────────────────────────────────────
# Automatically logs request metadata (user, IP, request_id, etc.)

DJANGO_STRUCTLOG_COMMAND_LOGGING_ENABLED = True