"""
User selectors (read-only queries).

Following Hacksoft styleguide: selectors are for reads, services are for writes.
"""

from uuid import UUID

from django.db.models import QuerySet

from src.apps.users.models import User


def get_user_by_id(*, user_id: UUID) -> User | None:
    return User.objects.filter(id=user_id).first()


def get_user_by_email(*, email: str) -> User | None:
    return User.objects.filter(email__iexact=email).first()


def get_active_users() -> QuerySet[User]:
    return User.objects.filter(is_active=True)


def user_exists(*, email: str) -> bool:
    return User.objects.filter(email__iexact=email).exists()
