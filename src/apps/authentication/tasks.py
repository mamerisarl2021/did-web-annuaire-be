import structlog
from celery import shared_task
from django.utils import timezone
from ninja_jwt.token_blacklist.models import OutstandingToken

logger = structlog.get_logger(__name__)

@shared_task
def clear_blacklisted_tokens():
    """
    Tâche périodique pour effacer les OutstandingTokens expirés.
    Par CASCADE, elle efface également les BlacklistedTokens associés.
    """
    now = timezone.now()
    try:
        # Supprime les jetons qui ont déjà expiré.
        deleted_count, _ = OutstandingToken.objects.filter(expires_at__lte=now).delete()
        if deleted_count > 0:
            logger.info("expired_tokens_cleared", count=deleted_count)
    except Exception as e:
        logger.error("expired_tokens_clear_failed", error=str(e))
