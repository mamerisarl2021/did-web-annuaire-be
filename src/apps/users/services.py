"""
User services (write operations).
"""

import structlog
from django.db import transaction
from django.utils import timezone

from .models import User
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
def update_user_profile(*, user: User, full_name: str | None = None, phone: str | None = None, functions: str | None = None) -> User:
    fields_to_update = ["updated_at"]
    if full_name is not None:
        user.full_name = full_name
        fields_to_update.append("full_name")
    if phone is not None:
        user.phone = phone
        fields_to_update.append("phone")
    if functions is not None:
        user.functions = functions
        fields_to_update.append("functions")
    user.save(update_fields=fields_to_update)
    return user

@transaction.atomic
def set_otp_secret(*, user: User, otp_secret: str) -> User:
    user.otp_secret = otp_secret
    user.save(update_fields=["otp_secret", "updated_at"])
    return user