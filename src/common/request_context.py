"""
Thread-local request context.

Stores per-request metadata (IP address, user agent, etc.) that service
functions can access without needing a ``request`` parameter threaded
through every call.

Populated by ``RequestContextMiddleware`` in middleware.py.
"""

import threading

_local = threading.local()


def set_request_ip(ip: str | None) -> None:
    _local.ip_address = ip


def get_request_ip() -> str | None:
    return getattr(_local, "ip_address", None)


def clear_request_context() -> None:
    _local.ip_address = None
