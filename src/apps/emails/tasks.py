"""
Email Celery tasks.

These run asynchronously via Celery. Each task renders an HTML template
and sends via the email service.
"""

import structlog
from celery import shared_task
from django.conf import settings
from django.template.loader import render_to_string

from src.apps.emails.services import email_send

logger = structlog.get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_activation_email(self, user_id: str, invitation_token: str, org_name: str):
    """
    Send account activation email after org approval.
    Contains the activation link with the invitation_token.
    """
    from src.apps.users.selectors import get_user_by_id

    try:
        user = get_user_by_id(user_id=user_id)
        if user is None:
            logger.warning("activation_email_user_not_found", user_id=user_id)
            return

        platform_domain = getattr(settings, "PLATFORM_DOMAIN", "localhost:8899")
        scheme = "https" if "localhost" not in platform_domain else "http"
        activation_url = f"{scheme}://{platform_domain}/activate/{invitation_token}/"

        html = render_to_string("emails/activation.html", {
            "user_name": user.full_name or user.email,
            "org_name": org_name,
            "activation_url": activation_url,
        })

        email_send(
            to=[user.email],
            subject=f"Welcome to AnnuaireDID — Activate your account",
            html=html,
        )

        logger.info("activation_email_sent", user_id=user_id, email=user.email)

    except Exception as exc:
        logger.error("activation_email_failed", user_id=user_id, error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_rejection_email(self, user_id: str, org_name: str, reason: str = ""):
    """Send organization rejection email."""
    from src.apps.users.selectors import get_user_by_id

    try:
        user = get_user_by_id(user_id=user_id)
        if user is None:
            return

        html = render_to_string("emails/rejection.html", {
            "user_name": user.full_name or user.email,
            "org_name": org_name,
            "reason": reason,
        })

        email_send(
            to=[user.email],
            subject=f"AnnuaireDID — Organization registration update",
            html=html,
        )

        logger.info("rejection_email_sent", user_id=user_id)

    except Exception as exc:
        logger.error("rejection_email_failed", user_id=user_id, error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_reset_email(self, user_id: str, reset_token: str):
    """Send password reset email."""
    from src.apps.users.selectors import get_user_by_id

    try:
        user = get_user_by_id(user_id=user_id)
        if user is None:
            return

        platform_domain = getattr(settings, "PLATFORM_DOMAIN", "localhost:8899")
        scheme = "https" if "localhost" not in platform_domain else "http"
        reset_url = f"{scheme}://{platform_domain}/reset-password/{reset_token}/"

        html = render_to_string("emails/password_reset.html", {
            "user_name": user.full_name or user.email,
            "reset_url": reset_url,
        })

        email_send(
            to=[user.email],
            subject="AnnuaireDID — Password reset",
            html=html,
        )

        logger.info("password_reset_email_sent", user_id=user_id)

    except Exception as exc:
        logger.error("password_reset_email_failed", user_id=user_id, error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_superadmin_new_registration_email(self, org_name: str, org_slug: str, admin_email: str):
    """Notify superadmins about a new organization registration."""
    from src.apps.users.models import User

    try:
        superadmin_emails = list(
            User.objects.filter(is_superadmin=True, is_active=True)
            .values_list("email", flat=True)
        )

        if not superadmin_emails:
            logger.warning("no_superadmins_to_notify")
            return

        platform_domain = getattr(settings, "PLATFORM_DOMAIN", "localhost:8899")
        scheme = "https" if "localhost" not in platform_domain else "http"
        review_url = f"{scheme}://{platform_domain}/superadmin/organizations/"

        html = render_to_string("emails/new_registration.html", {
            "org_name": org_name,
            "org_slug": org_slug,
            "admin_email": admin_email,
            "review_url": review_url,
        })

        email_send(
            to=superadmin_emails,
            subject=f"AnnuaireDID — New organization registration: {org_name}",
            html=html,
        )

        logger.info("superadmin_notified", org_name=org_name)

    except Exception as exc:
        logger.error("superadmin_notification_failed", error=str(exc))
        raise self.retry(exc=exc)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_member_invitation_email(
    self,
    user_id: str,
    invitation_token: str,
    org_name: str,
    role: str,
    invited_by_name: str,
):
    """
    Send invitation email to a newly invited org member.
    Distinct from send_activation_email — this makes it clear the user
    was invited by someone, shows their role, and uses 'Accept Invitation' CTA.
    """
    from src.apps.users.selectors import get_user_by_id

    try:
        user = get_user_by_id(user_id=user_id)
        if user is None:
            logger.warning("invitation_email_user_not_found", user_id=user_id)
            return

        platform_domain = getattr(settings, "PLATFORM_DOMAIN", "localhost:8899")
        scheme = "https" if "localhost" not in platform_domain else "http"
        activation_url = f"{scheme}://{platform_domain}/activate/{invitation_token}/"

        role_display = {
            "ORG_MEMBER": "Member — can manage documents & certificates",
            "AUDITOR": "Auditor — read-only access",
            "ORG_ADMIN": "Admin — full access",
        }.get(role, role)

        html = render_to_string("emails/member_invitation.html", {
            "user_name": user.full_name or None,
            "org_name": org_name,
            "role": role,
            "role_display": role_display,
            "invited_by": invited_by_name,
            "activation_url": activation_url,
        })

        email_send(
            to=[user.email],
            subject=f"You've been invited to {org_name} on AnnuaireDID",
            html=html,
        )

        logger.info("invitation_email_sent", user_id=user_id, email=user.email, org=org_name)

    except Exception as exc:
        logger.error("invitation_email_failed", user_id=user_id, error=str(exc))
        raise self.retry(exc=exc)