"""
Sélecteurs d'organisation (opérations de lecture).
"""

from django.db.models import QuerySet

from src.apps.organizations.models import Membership, Organization
from src.apps.users.models import User
from src.common.types import MembershipStatus


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


def get_user_organizations(*, user: User) -> QuerySet[Organization]:
    """Retourne toutes les organisations où l'utilisateur a une adhésion active."""
    org_ids = Membership.objects.filter(
        user=user, status=MembershipStatus.ACTIVE
    ).values_list("organization_id", flat=True)
    return Organization.objects.filter(id__in=org_ids).order_by("-created_at")


def get_active_membership(
    *, user: User, organization: Organization
) -> Membership | None:
    try:
        return Membership.objects.get(
            user=user,
            organization=organization,
            status=MembershipStatus.ACTIVE,
        )
    except Membership.DoesNotExist:
        return None


def get_membership_by_invitation_token(*, token) -> Membership | None:
    try:
        return Membership.objects.select_related("user", "organization").get(
            invitation_token=token
        )
    except Membership.DoesNotExist:
        return None


def get_organization_members(*, organization_id) -> QuerySet[Membership]:
    """Retourne tous les membres d'une organisation."""
    return (
        Membership.objects.filter(organization_id=organization_id)
        .select_related("user", "invited_by")
        .order_by(
            # ORG_ADMIN en premier, puis par date de création
            "-role",
            "-created_at",
        )
    )


def get_pending_organizations() -> QuerySet[Organization]:
    from src.common.types import OrgStatus

    return Organization.objects.filter(status=OrgStatus.PENDING_REVIEW).order_by(
        "-created_at"
    )


def get_organization_stats(*, organization_id, user_id=None) -> dict:
    """
    Retourne les statistiques de l'organisation.
    Si `user_id` est fourni, filtre les docs/certs par utilisateur (scope "me").
    """
    from src.apps.documents.models import DIDDocument, DocumentStatus
    from src.apps.certificates.models import Certificate

    members = Membership.objects.filter(organization_id=organization_id)

    if user_id:
        my_docs = DIDDocument.objects.filter(organization_id=organization_id, owner_id=user_id)
        return {
            "total_members": 0,
            "active_members": 0,
            "invited_members": 0,
            "total_documents": my_docs.count(),
            "draft_documents": my_docs.filter(status=DocumentStatus.DRAFT).count(),
            "signed_documents": my_docs.filter(
                status__in=[DocumentStatus.SIGNED, DocumentStatus.PUBLISHED]
            ).count(),
            "published_documents": my_docs.filter(status=DocumentStatus.PUBLISHED).count(),
            "total_certificates": Certificate.objects.filter(
                organization_id=organization_id, created_by_id=user_id
            ).count(),
        }

    org_docs = DIDDocument.objects.filter(organization_id=organization_id)
    return {
        "total_members": members.exclude(status=MembershipStatus.DEACTIVATED).count(),
        "active_members": members.filter(status=MembershipStatus.ACTIVE).count(),
        "invited_members": members.filter(status=MembershipStatus.INVITED).count(),
        "total_documents": org_docs.count(),
        "draft_documents": org_docs.filter(status=DocumentStatus.DRAFT).count(),
        "signed_documents": org_docs.filter(
            status__in=[DocumentStatus.SIGNED, DocumentStatus.PUBLISHED]
        ).count(),
        "published_documents": org_docs.filter(status=DocumentStatus.PUBLISHED).count(),
        "total_certificates": Certificate.objects.filter(
            organization_id=organization_id
        ).count(),
    }
