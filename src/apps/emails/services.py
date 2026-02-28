"""
Email sending service.

Wraps Django's email backend with a stable API.
"""

import re
from typing import Any

from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives, get_connection
from django.db import transaction
from django.utils.html import strip_tags


def _fallback_plain_text(html: str) -> str:
    text = strip_tags(html)
    return re.sub(r"\s+\n", "\n", re.sub(r"[ \t]+", " ", text)).strip()

@transaction.atomic
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
    Send an email using Django's email backend.

    Returns True if sent successfully.
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
