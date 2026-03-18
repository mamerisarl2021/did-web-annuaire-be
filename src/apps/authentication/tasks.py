from urllib.parse import urlencode
from datetime import timedelta
import structlog
from celery import shared_task
from django.utils import timezone
from ninja_jwt.token_blacklist.models import OutstandingToken, BlacklistedToken

logger = structlog.get_logger(__name__)

@shared_task
def clear_blacklisted_tokens():
    """
    Periodic task to clear expired OutstandingTokens. 
    By CASCADE, it also clears the associated BlacklistedTokens.
    """
    now = timezone.now()
    try:
        # Delete tokens that have already expired.
        deleted_count, _ = OutstandingToken.objects.filter(expires_at__lte=now).delete()
        if deleted_count > 0:
            logger.info("expired_tokens_cleared", count=deleted_count)
    except Exception as e:
        logger.error("expired_tokens_clear_failed", error=str(e))
