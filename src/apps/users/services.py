"""
Services utilisateur (opérations d'écriture).
"""

import structlog
from django.db import transaction
from django.utils import timezone

from .models import User
from src.apps.audits.models import AuditAction, ResourceType
from src.apps.audits.services import log_action
from src.common.exceptions import ConflictError, ValidationError

logger = structlog.get_logger(__name__)


@transaction.atomic
def create_user(
    *,
    email: str,
    full_name: str,
    password: str,
    phone: str = "",
    functions: str = "",
    is_active: bool = False,
) -> User:
    email = email.lower().strip()

    if User.objects.filter(email__iexact=email).exists():
        raise ConflictError(f"A user with email '{email}' already exists.")

    user = User.objects.create_user(
        email=email,
        password=password,
        full_name=full_name,
        phone=phone,
        functions=functions,
        is_active=is_active,
    )

    logger.info("user_created", user_id=str(user.id), email=user.email)
    return user


@transaction.atomic
def activate_user(*, user: User) -> User:
    if user.is_active:
        raise ValidationError("Account is already activated.")

    user.is_active = True
    user.account_activated_at = timezone.now()
    user.save(update_fields=["is_active", "account_activated_at", "updated_at"])

    logger.info("user_activated", user_id=str(user.id))
    return user


@transaction.atomic
def update_user_profile(
    *,
    user: User,
    full_name: str | None = None,
    phone: str | None = None,
    functions: str | None = None,
    email: str | None = None,
) -> User:
    fields_to_update = ["updated_at"]
    metadata = {}

    if email is not None:
        email = email.lower().strip()
        if user.email != email:
            if User.objects.filter(email__iexact=email).exists():
                raise ConflictError(f"A user with email '{email}' already exists.")
            user.email = email
            fields_to_update.append("email")
            metadata["email"] = email

    if full_name is not None and user.full_name != full_name:
        user.full_name = full_name
        fields_to_update.append("full_name")
        metadata["full_name"] = full_name

    if phone is not None and user.phone != phone:
        user.phone = phone
        fields_to_update.append("phone")
        metadata["phone"] = phone

    if functions is not None and user.functions != functions:
        user.functions = functions
        fields_to_update.append("functions")
        metadata["functions"] = functions

    if len(fields_to_update) > 1:
        user.save(update_fields=fields_to_update)

        log_action(
            actor=user,
            action=AuditAction.USER_UPDATED,
            resource_type=ResourceType.USER,
            resource_id=user.id,
            description=f"User '{user.email}' updated their profile.",
            metadata=metadata,
        )

        logger.info(
            "user_profile_updated",
            user_id=str(user.id),
            updated_fields=fields_to_update,
        )

    return user


@transaction.atomic
def set_otp_secret(*, user: User, otp_secret: str) -> User:
    user.otp_secret = otp_secret
    user.save(update_fields=["otp_secret", "updated_at"])

    logger.debug("otp_secret_set", user_id=str(user.id))
    return user


@transaction.atomic
def delete_user(*, user: User, deleted_by: User) -> None:
    log_action(
        actor=deleted_by,
        action=AuditAction.USER_UPDATED,  # ou ajouter USER_DELETED
        resource_type=ResourceType.USER,
        resource_id=user.id,
        description=f"User '{user.email}' deleted.",
    )
    logger.info("user_deleted", user_id=str(user.id))
    user.delete()
