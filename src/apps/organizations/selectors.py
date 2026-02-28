"""
Organization selectors (read operations).
"""

from uuid import UUID

from django.db.models import QuerySet

from src.apps.organizations.models import Membership, Organization
from src.apps.users.models import User
from src.common.types import MembershipStatus, Role


def get_organization_by_id(*, org_id) -> Organization | None:
    try:
        return Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return None


def get_organization_by_slug(*, slug: str) -> Organization | None:
    try:
        return Organization.objects.get(slug=slug)
    except Organization.DoesNotExist:
        return None


def get_user_organizations(*, user: User) -> list[Organization]:
    """Return all organizations where the user has an active membership."""
    org_ids = (
        Membership.objects
        .filter(user=user, status=MembershipStatus.ACTIVE)
        .values_list("organization_id", flat=True)
    )
    return list(
        Organization.objects
        .filter(id__in=org_ids)
        .order_by("-created_at")
    )


def get_active_membership(*, user: User, organization: Organization) -> Membership | None:
    try:
        return Membership.objects.get(
            user=user, organization=organization, status=MembershipStatus.ACTIVE,
        )
    except Membership.DoesNotExist:
        return None


def get_membership_by_invitation_token(*, token) -> Membership | None:
    try:
        return (
            Membership.objects
            .select_related("user", "organization")
            .get(invitation_token=token)
        )
    except Membership.DoesNotExist:
        return None


def get_organization_members(*, organization_id) -> list[Membership]:
    """Return all members (excluding deactivated) for an organization."""
    return list(
        Membership.objects
        .filter(organization_id=organization_id)
        .select_related("user", "invited_by")
        .order_by(
            # ORG_ADMIN first, then by creation date
            "-role",
            "-created_at",
        )
    )


def get_pending_organizations() -> QuerySet[Organization]:
    from src.common.types import OrgStatus
    return Organization.objects.filter(status=OrgStatus.PENDING_REVIEW).order_by("-created_at")