"""
Service d'envoi d'e-mails.

Enveloppe le backend d'e-mail de Django avec une API stable.
"""

import re
from typing import Any

import structlog
from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives, get_connection
from django.utils.html import strip_tags
from django.utils import timezone

from src.apps.emails.models import Email

logger = structlog.get_logger(__name__)


def _fallback_plain_text(html: str) -> str:
    text = strip_tags(html)
    return re.sub(r"\s+\n", "\n", re.sub(r"[ \t]+", " ", text)).strip()


def email_send(
    *,
    to: list[str],
    subject: str,
    html: str | None = None,
    text: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    reply_to: list[str] | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
    extra_headers: dict[str, str] | None = None,
    connection_kwargs: dict[str, Any] | None = None,
) -> bool:
    """
    Envoyer un e-mail en utilisant le backend d'e-mail de Django.

    Renvoie True en cas d'envoi réussi.

    Note: pas de @transaction.atomic — cette fonction n'effectue aucune
    opération sur la base de données. L'encapsuler dans une transaction
    maintiendrait une connexion DB ouverte pendant toute la durée de
    la connexion SMTP, ce qui dégraderait inutilement les performances.
    """
    connection = get_connection(**(connection_kwargs or {}))
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@didannuaire.com")

    if html:
        plain = text or _fallback_plain_text(html)
        message = EmailMultiAlternatives(
            subject=subject,
            body=plain,
            from_email=from_email,
            to=to,
            cc=cc or [],
            bcc=bcc or [],
            reply_to=reply_to or [],
            headers=extra_headers or {},
            connection=connection,
        )
        message.attach_alternative(html, "text/html")
    else:
        message = EmailMessage(
            subject=subject,
            body=(text or ""),
            from_email=from_email,
            to=to,
            cc=cc or [],
            bcc=bcc or [],
            reply_to=reply_to or [],
            headers=extra_headers or {},
            connection=connection,
        )

    for att in attachments or []:
        filename, content, mimetype = att
        message.attach(filename, content, mimetype)

    sent = message.send(fail_silently=False)
    return sent > 0


def create_outbox_email(
    *,
    to: str,
    subject: str,
    html: str,
    task_name: str,
    metadata: dict | None = None,
) -> Email:
    return Email.objects.create(
        to=to,
        subject=subject,
        html=html,
        plain_text=_fallback_plain_text(html),
        task_name=task_name,
        metadata=metadata or {},
        status=Email.Status.READY,
    )


def mark_outbox_sending(outbox_id: str) -> None:
    Email.objects.filter(id=outbox_id).update(
        status=Email.Status.SENDING,
        last_error="",
    )


def mark_outbox_sent(outbox_id: str) -> None:
    Email.objects.filter(id=outbox_id).update(
        status=Email.Status.SENT,
        sent_at=timezone.now(),
        last_error="",
    )


def mark_outbox_failed(outbox_id: str, error: str, *, permanent: bool = False) -> None:
    status = Email.Status.FAILED if permanent else Email.Status.READY
    Email.objects.filter(id=outbox_id).update(status=status, last_error=error)
    if permanent:
        email = Email.objects.filter(id=outbox_id).values("task_name", "to").first()
        logger.error(
            "email_delivery_failed_permanently",
            outbox_id=outbox_id,
            task_name=email["task_name"] if email else "",
            to=email["to"] if email else "",
            error=error,
        )
