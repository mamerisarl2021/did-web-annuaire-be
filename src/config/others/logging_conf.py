"""
Configuration du journal avec structlog + django-structlog.

Développement : sortie console colorée et lisible.
Production : lignes JSON (un objet JSON par ligne).

Le basculement est automatique selon DJANGO_ENV.
"""

import structlog

from src.config.env import env


# ── Processeurs partagés structlog ──────────────────────────────────────
# Exécutés pour chaque événement de journal, quel que soit l'environnement.

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

# ── Rendu spécifique à l'environnement ──────────────────────────────────

if env.is_production:
    # Rendu JSON pour la production (un objet JSON par ligne)
    renderer = structlog.processors.JSONRenderer()
else:
    # Sortie colorée et lisible pour le développement
    renderer = structlog.dev.ConsoleRenderer(colors=True)


# ── Configuration de structlog ──────────────────────────────────────────

structlog.configure(
    processors=[
        *shared_processors,
        # Préparation pour l'intégration de la journalisation stdlib
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)


# ── Dictionnaire LOGGING de Django ──────────────────────────────────────
# Routage de la journalisation stdlib de Django via ProcessorFormatter.

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
            "level": "WARNING",  # Supprime le bruit SQL sauf en débogage
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
# Journalise automatiquement les métadonnées (utilisateur, IP, etc.)

DJANGO_STRUCTLOG_COMMAND_LOGGING_ENABLED = True
