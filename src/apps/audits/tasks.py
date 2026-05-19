from celery import shared_task
import structlog
from src.apps.audits.models import AuditLog

logger = structlog.get_logger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def async_log_action(
    self,
    actor_id,
    actor_email: str,
    organization_id,
    organization_name: str,
    action: str,
    resource_type: str,
    resource_id,
    description: str,
    metadata: dict,
    ip_address: str | None,
):
    """
    Celery task to create an audit log asynchronously.
    """
    try:
        entry = AuditLog.objects.create(
            actor_id=actor_id,
            actor_email=actor_email,
            organization_id=organization_id,
            organization_name=organization_name,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            description=description,
            metadata=metadata or {},
            ip_address=ip_address,
        )

        logger.info(
            "audit_logged_async",
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            actor=actor_email,
            ip_address=ip_address,
        )
        return str(entry.id)
    except Exception as exc:
        logger.error("async_log_action_failed", error=str(exc))
        raise self.retry(exc=exc) from exc
