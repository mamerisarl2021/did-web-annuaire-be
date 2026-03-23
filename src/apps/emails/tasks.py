"""
Tâches Celery pour les e-mails.

S'exécutent de manière asynchrone via Celery. Chq t. rend un modèle HTML
et l'envoie via le service d'e-mail.
"""

from urllib.parse import urlparse

import structlog
from celery import shared_task
from django.conf import settings
from django.template.loader import render_to_string

from src.apps.emails.services import email_send

logger = structlog.get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_activation_email(self, user_id: str, invitation_token: str, org_name: str):
    """
    Envoyer un e-mail d'activ. de cmpte après l'approbation de l'org.
    Contient le lien d'activation avec le invitation_token.
    """
    from src.apps.users.selectors import get_user_by_id

    try:
        user = get_user_by_id(user_id=user_id)
        if user is None:
            logger.warning("activation_email_user_not_found", user_id=user_id)
            return

        platform_domain = settings.PLATFORM_DOMAIN
        activation_url = f"{platform_domain}/activate/{invitation_token}/"

        html = render_to_string(
            "emails/activation.html",
            {
                "user_name": user.full_name or user.email,
                "org_name": org_name,
                "activation_url": activation_url,
            },
        )

        email_send(
            to=[user.email],
            subject="Welcome to AnnuaireDID — Activate your account",
            html=html,
        )

        logger.info("activation_email_sent", user_id=user_id, email=user.email)

    except Exception as exc:
        logger.error("activation_email_failed", user_id=user_id, error=str(exc))
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_rejection_email(self, user_id: str, org_name: str, reason: str = ""):
    """Envoyer un e-mail de rejet d'organisation."""
    from src.apps.users.selectors import get_user_by_id

    try:
        user = get_user_by_id(user_id=user_id)
        if user is None:
            return

        html = render_to_string(
            "emails/rejection.html",
            {
                "user_name": user.full_name or user.email,
                "org_name": org_name,
                "reason": reason,
            },
        )

        email_send(
            to=[user.email],
            subject="AnnuaireDID — Organization registration update",
            html=html,
        )

        logger.info("rejection_email_sent", user_id=user_id)

    except Exception as exc:
        logger.error("rejection_email_failed", user_id=user_id, error=str(exc))
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_reset_email(self, user_id: str, reset_token: str):
    """Envoyer un e-mail de réinitialisation de mot de passe."""
    from src.apps.users.selectors import get_user_by_id

    try:
        user = get_user_by_id(user_id=user_id)
        if user is None:
            return

        platform_domain = settings.PLATFORM_DOMAIN
        reset_url = f"{platform_domain}/reset-password/{reset_token}/"

        html = render_to_string(
            "emails/password_reset.html",
            {
                "user_name": user.full_name or user.email,
                "reset_url": reset_url,
            },
        )

        email_send(
            to=[user.email],
            subject="AnnuaireDID — Password reset",
            html=html,
        )

        logger.info("password_reset_email_sent", user_id=user_id)

    except Exception as exc:
        logger.error("password_reset_email_failed", user_id=user_id, error=str(exc))
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_superadmin_new_registration_email(
    self, org_name: str, org_slug: str, admin_email: str
):
    """Informer les superadmins d'une nouvelle inscr d'organisation."""
    from src.apps.users.models import User

    try:
        superadmin_emails = list(
            User.objects.filter(is_superadmin=True, is_active=True).values_list(
                "email", flat=True
            )
        )

        if not superadmin_emails:
            logger.warning("no_superadmins_to_notify")
            return

        platform_domain = settings.PLATFORM_DOMAIN
        review_url = f"{platform_domain}/superadmin/organizations/"

        html = render_to_string(
            "emails/new_registration.html",
            {
                "org_name": org_name,
                "org_slug": org_slug,
                "admin_email": admin_email,
                "review_url": review_url,
            },
        )

        email_send(
            to=superadmin_emails,
            subject=f"AnnuaireDID — New organization registration: {org_name}",
            html=html,
        )

        logger.info("superadmin_notified", org_name=org_name)

    except Exception as exc:
        logger.error("superadmin_notification_failed", error=str(exc))
        raise self.retry(exc=exc) from exc


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
    Env. un e-mail d'invit. à un membre de l'org nouvellement invité.
    D. de send_activation_email — rend clair que l'utilisateur 
    a été inv. par qn, mf son rôle et util le CTA 'Accept Invitation'.
    """
    from src.apps.users.selectors import get_user_by_id

    try:
        user = get_user_by_id(user_id=user_id)
        if user is None:
            logger.warning("invitation_email_user_not_found", user_id=user_id)
            return

        platform_domain = getattr(settings, "PLATFORM_DOMAIN", "localhost:8899")
        parsed = urlparse(platform_domain)
        host = parsed.netloc or parsed.path  # gère les cas sans schéma
        scheme = "https" if "localhost" not in host else "http"
        activation_url = f"{scheme}://{host}/activate/{invitation_token}/"

        role_display = {
            "ORG_MEMBER": "Member — can manage documents & certificates",
            "AUDITOR": "Auditor — read-only access",
            "ORG_ADMIN": "Admin — full access",
        }.get(role, role)

        html = render_to_string(
            "emails/member_invitation.html",
            {
                "user_name": user.full_name or None,
                "org_name": org_name,
                "role": role,
                "role_display": role_display,
                "invited_by": invited_by_name,
                "activation_url": activation_url,
            },
        )

        email_send(
            to=[user.email],
            subject=f"You've been invited to {org_name} on AnnuaireDID",
            html=html,
        )

        logger.info(
            "invitation_email_sent", user_id=user_id, email=user.email, org=org_name
        )

    except Exception as exc:
        logger.error("invitation_email_failed", user_id=user_id, error=str(exc))
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_document_submitted_email(self, doc_id: str, org_id: str, submitter_id: str):
    from src.apps.documents.selectors import get_document_by_id
    from src.apps.organizations.selectors import (
        get_organization_by_id,
        get_organization_members,
    )
    from src.apps.users.selectors import get_user_by_id

    try:
        doc = get_document_by_id(doc_id=doc_id)
        org = get_organization_by_id(org_id=org_id)
        submitter = get_user_by_id(user_id=submitter_id)

        if not doc or not org or not submitter:
            return

        members = get_organization_members(organization_id=org_id)
        admin_emails = [
            m.user.email for m in members if m.role == "ORG_ADMIN" and m.user.is_active
        ]

        if not admin_emails:
            return

        platform_domain = getattr(settings, "PLATFORM_DOMAIN", "localhost:8899")
        parsed = urlparse(platform_domain)
        host = parsed.netloc or parsed.path  # gère les cas sans schéma
        scheme = "https" if "localhost" not in host else "http"
        review_url = f"{scheme}://{host}/workspace/documents/"

        html = render_to_string(
            "emails/document_submitted.html",
            {
                "submitter_name": submitter.full_name or submitter.email,
                "doc_label": doc.label,
                "org_name": org.name,
                "review_url": review_url,
            },
        )

        email_send(
            to=admin_emails,
            subject=f"AnnuaireDID — Document submitted for review: {doc.label}",
            html=html,
        )

    except Exception as exc:
        logger.error("send_document_submitted_email_failed", error=str(exc))
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_document_reviewed_email(
    self, doc_id: str, org_id: str, reviewer_id: str, action: str, reason: str = ""
):
    from src.apps.documents.selectors import get_document_by_id
    from src.apps.organizations.selectors import get_organization_by_id
    from src.apps.users.selectors import get_user_by_id

    try:
        doc = get_document_by_id(doc_id=doc_id)
        org = get_organization_by_id(org_id=org_id)
        reviewer = get_user_by_id(user_id=reviewer_id)

        if not doc or not org or not reviewer or not doc.submitted_by:
            return

        platform_domain = getattr(settings, "PLATFORM_DOMAIN", "localhost:8899")
        parsed = urlparse(platform_domain)
        host = parsed.netloc or parsed.path  # gère les cas sans schéma
        scheme = "https" if "localhost" not in host else "http"
        doc_url = f"{scheme}://{host}/workspace/documents/{doc.id}"

        submitter = doc.submitted_by

        html = render_to_string(
            "emails/document_reviewed.html",
            {
                "submitter_name": submitter.full_name or submitter.email,
                "doc_label": doc.label,
                "org_name": org.name,
                "action": action,
                "reviewer_name": reviewer.full_name or reviewer.email,
                "reason": reason,
                "doc_url": doc_url,
            },
        )

        email_send(
            to=[submitter.email],
            subject=f"AnnuaireDID — Document {action}: {doc.label}",
            html=html,
        )

    except Exception as exc:
        logger.error("send_document_reviewed_email_failed", error=str(exc))
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_organization_suspended_email(self, user_id: str, org_name: str, reason: str = ""):
    from src.apps.users.selectors import get_user_by_id

    try:
        user = get_user_by_id(user_id=user_id)
        if user is None:
            return

        html = f"""
        <p>Dear {user.full_name or user.email},</p>
        <p>Your organization <strong>{org_name}</strong> has been suspended.</p>
        """
        if reason:
            html += f"<p>Reason: {reason}</p>"

        email_send(
            to=[user.email],
            subject=f"AnnuaireDID — Organization Suspended: {org_name}",
            html=html,
        )
        logger.info("suspension_email_sent", user_id=user_id)

    except Exception as exc:
        logger.error("suspension_email_failed", user_id=user_id, error=str(exc))
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_organization_reactivated_email(self, user_id: str, org_name: str):
    from src.apps.users.selectors import get_user_by_id

    try:
        user = get_user_by_id(user_id=user_id)
        if user is None:
            return

        html = f"""
        <p>Dear {user.full_name or user.email},</p>
        <p>Your organization <strong>{org_name}</strong> has been successfully reactivated. Your access to the platform has been restored.</p>
        """

        email_send(
            to=[user.email],
            subject=f"AnnuaireDID — Organization Reactivated: {org_name}",
            html=html,
        )
        logger.info("reactivation_email_sent", user_id=user_id)

    except Exception as exc:
        logger.error("reactivation_email_failed", user_id=user_id, error=str(exc))
        raise self.retry(exc=exc) from exc
