"""
Organization selectors (read-only queries).
"""

from uuid import UUID

from django.db.models import QuerySet

from src.common.types import MembershipStatus

from .models import Membership, Organization

def get_organization_by_id(*, org_id: UUID) -> Organization | None:
    return Organization.objects.filter(id=org_id).first()


def get_organization_by_slug(*, slug: str) -> Organization | None:
    return Organization.objects.filter(slug=slug).first()


def get_user_organizations(*, user) -> QuerySet[Organization]:
    """Get all organizations the user is an active member of."""
    org_ids = Membership.objects.filter(
        user=user,
        status=MembershipStatus.ACTIVE,
    ).values_list("organization_id", flat=True)
    return Organization.objects.filter(id__in=org_ids)


def get_active_membership(*, user, organization_id: UUID) -> Membership | None:
    """Get the user's active membership in a specific organization."""
    return Membership.objects.filter(
        user=user,
        organization_id=organization_id,
        status=MembershipStatus.ACTIVE,
    ).select_related("organization").first()


def get_membership_by_invitation_token(*, token: UUID) -> Membership | None:
    """Look up a membership by its invitation token (for activation)."""
    return (
        Membership.objects
        .filter(invitation_token=token)
        .select_related("user", "organization")
        .first()
    )


def get_organization_members(*, organization_id: UUID) -> QuerySet[Membership]:
    """Get all memberships for an organization."""
    return (
        Membership.objects
        .filter(organization_id=organization_id)
        .select_related("user", "invited_by")
        .order_by("role", "-created_at")
    )


def get_pending_organizations() -> QuerySet[Organization]:
    """Get organizations awaiting superadmin review."""
    from src.common.types import OrgStatus
    return Organization.objects.filter(status=OrgStatus.PENDING_REVIEW)
