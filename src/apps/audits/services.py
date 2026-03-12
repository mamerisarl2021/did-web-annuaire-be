"""
Audit log service.

Provides a simple API to create immutable audit entries.
"""

import structlog
from django.db import transaction

from src.apps.audits.models import AuditLog

logger = structlog.get_logger(__name__)


@transaction.atomic
def log_action(
    *,
    actor,
    action: str,
    resource_type: str,
    resource_id,
    organization=None,
    description: str = "",
    metadata: dict | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """
    Create an audit log entry.

    Args:
        actor: User instance (or None for system actions)
        action: AuditAction value
        resource_type: ResourceType value
        resource_id: UUID of the affected resource
        organization: Organization instance (optional)
        description: Human-readable summary
        metadata: Extra context dict
        ip_address: Request IP. If None, automatically read from
            the thread-local request context (set by middleware).

    Returns:
        AuditLog instance
    """
    # Auto-read IP from middleware context if not explicitly provided
    if ip_address is None:
        from src.common.request_context import get_request_ip
        ip_address = get_request_ip()

    entry = AuditLog.objects.create(
        actor=actor,
        actor_email=getattr(actor, "email", "system"),
        organization=organization,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        description=description,
        metadata=metadata or {},
        ip_address=ip_address,
    )

    logger.info(
        "audit_logged",
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        actor=entry.actor_email,
        ip_address=ip_address,
    )

    return entry


def get_client_ip(request) -> str | None:
    """
    Extract client IP from a Django request, handling reverse proxies.

    Checks X-Forwarded-For (set by nginx) first, then falls back
    to REMOTE_ADDR.

    Note: This is intentionally NOT wrapped in @transaction.atomic —
    it's a pure read helper, not a DB operation.
    """
    if request is None:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")