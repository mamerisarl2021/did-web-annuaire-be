"""
Gunicorn configuration.

Reads from pydantic_settings env for worker count and bind address.
structlog handles all logging — gunicorn's default loggers are suppressed.
"""

import multiprocessing

from src.config.env import env

# ── Server socket ───────────────────────────────────────────────────────

bind = env.GUNICORN_BIND  # "0.0.0.0:8899"

# ── Workers ─────────────────────────────────────────────────────────────

workers = env.GUNICORN_WORKERS or (multiprocessing.cpu_count() * 2 + 1)
worker_class = "sync"
worker_tmp_dir = "/dev/shm"  # Faster heartbeat checks in Docker

# ── Timeouts ────────────────────────────────────────────────────────────

timeout = 120
graceful_timeout = 30
keepalive = 5

# ── Logging ─────────────────────────────────────────────────────────────
# Let structlog handle all formatting. Gunicorn just logs to stderr.

accesslog = "-"
errorlog = "-"
loglevel = "info"

# ── Process naming ──────────────────────────────────────────────────────

proc_name = "annuaire-did"

# ── Security ────────────────────────────────────────────────────────────

limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190