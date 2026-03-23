"""
Service de journalisation d'audit.
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
    Créer une entrée de journal d'audit.

    Arguments :
        actor: Instance User (ou None pour les actions système)
        action: Valeur AuditAction
        resource_type: Valeur ResourceType
        resource_id: UUID de la ressource concernée
        organization: Instance Organization (optionnel)
        description: Résumé lisible par l'homme
        metadata: Dictionnaire de contexte supplémentaire
        ip_address: IP de req. Si None, lu auto dans le contexte local.

    Retours :
        Instance AuditLog
    """
    # Lecture auto de l'IP depuis le mw si non fournie explicitement
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
    Extrait l'IP du client depuis une requête Django.

    Vérifie d'abord X-Forwarded-For (par nginx), puis REMOTE_ADDR.
    """
    if request is None:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
