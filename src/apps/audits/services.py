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
        ip_address: Request IP (optional)

    Returns:
        AuditLog instance
    """
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
    )

    return entry

@transaction.atomic
def get_client_ip(request) -> str | None:
    """Extract client IP from Django request, handling proxies."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")