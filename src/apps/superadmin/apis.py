"""
Superadmin API endpoints.

All endpoints require JWT auth + is_superadmin.
"""

from uuid import UUID

from django.http import HttpRequest
from ninja import Query, Router
from ninja_jwt.authentication import JWTAuth

from src.apps.organizations.models import Membership, Organization
from src.apps.organizations.selectors import (
    get_organization_by_id,
    get_organization_members,
)
from src.apps.organizations import services as org_services
from src.apps.superadmin.schemas import (
    AdminUserSchema,
    DashboardStatsSchema,
    ErrorSchema,
    FileResponseSchema,
    MessageSchema,
    OrgDetailSchema,
    OrgListItemSchema,
    OrgRejectSchema,
    OrgSuspendSchema,
)
from src.apps.users.models import User
from src.common.exceptions import NotFoundError
from src.common.permissions import require_superadmin
from src.common.types import MembershipStatus, OrgStatus, Role

router = Router(tags=["Superadmin"])


def _ensure_superadmin(request):
    require_superadmin(request.auth)


# ── Dashboard stats ─────────────────────────────────────────────────────


@router.get(
    "/dashboard",
    response=DashboardStatsSchema,
    auth=JWTAuth(),
    summary="Dashboard statistics",
)
def dashboard_stats(request: HttpRequest):
    _ensure_superadmin(request)

    return {
        "pending_count": Organization.objects.filter(status=OrgStatus.PENDING_REVIEW).count(),
        "approved_count": Organization.objects.filter(status=OrgStatus.APPROVED).count(),
        "rejected_count": Organization.objects.filter(status=OrgStatus.REJECTED).count(),
        "suspended_count": Organization.objects.filter(status=OrgStatus.SUSPENDED).count(),
        "total_users": User.objects.count(),
        "active_users": User.objects.filter(is_active=True).count(),
    }


# ── Organization list ───────────────────────────────────────────────────


@router.get(
    "/organizations",
    response=list[OrgListItemSchema],
    auth=JWTAuth(),
    summary="List organizations with optional status filter",
)
def list_organizations(
    request: HttpRequest,
    status: str = Query(None, description="Filter by status: PENDING_REVIEW, APPROVED, REJECTED, SUSPENDED"),
):
    _ensure_superadmin(request)

    qs = Organization.objects.select_related("created_by").order_by("-created_at")
    if status:
        qs = qs.filter(status=status)

    results = []
    for org in qs:
        # Get the org admin email
        admin_membership = Membership.objects.filter(
            organization=org, role=Role.ORG_ADMIN
        ).select_related("user").first()

        results.append({
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "type": org.type,
            "country": org.country,
            "email": org.email,
            "status": org.status,
            "created_at": org.created_at.isoformat(),
            "admin_email": admin_membership.user.email if admin_membership else None,
        })

    return results


# ── Organization detail ─────────────────────────────────────────────────


@router.get(
    "/organizations/{org_id}",
    response={200: OrgDetailSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Get organization details",
)
def get_organization(request: HttpRequest, org_id: UUID):
    _ensure_superadmin(request)

    org = (
        Organization.objects
        .select_related("authorization_document", "justification_document", "created_by", "reviewed_by")
        .filter(id=org_id)
        .first()
    )
    if org is None:
        raise NotFoundError("Organization not found.")

    # Get org admin
    admin_membership = (
        Membership.objects
        .filter(organization=org, role=Role.ORG_ADMIN)
        .select_related("user")
        .first()
    )

    member_count = Membership.objects.filter(organization=org).count()

    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "type": org.type,
        "description": org.description,
        "country": org.country,
        "address": org.address,
        "email": org.email,
        "status": org.status,
        "rejection_reason": org.rejection_reason,
        "created_at": org.created_at.isoformat(),
        "reviewed_at": org.reviewed_at.isoformat() if org.reviewed_at else None,
        "authorization_document": _file_dict(org.authorization_document),
        "justification_document": _file_dict(org.justification_document),
        "admin_user": _admin_dict(admin_membership),
        "member_count": member_count,
    }


def _file_dict(file_obj):
    if file_obj is None:
        return None
    return {
        "id": file_obj.id,
        "original_file_name": file_obj.original_file_name,
        "file_type": file_obj.file_type,
        "file_size": file_obj.file_size,
        "url": file_obj.url,
    }


def _admin_dict(membership):
    if membership is None:
        return None
    u = membership.user
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "phone": u.phone,
        "functions": u.functions,
        "is_active": u.is_active,
    }


# ── Approve ─────────────────────────────────────────────────────────────


@router.post(
    "/organizations/{org_id}/approve",
    response={200: MessageSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Approve an organization",
)
def approve_organization(request: HttpRequest, org_id: UUID):
    _ensure_superadmin(request)

    org = get_organization_by_id(org_id=org_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    org = org_services.approve_organization(organization=org, reviewed_by=request.auth)

    # Send activation email to the org admin
    admin_membership = Membership.objects.filter(
        organization=org, role=Role.ORG_ADMIN
    ).select_related("user").first()

    if admin_membership:
        from src.apps.emails.tasks import send_activation_email

        send_activation_email.delay(
            user_id=str(admin_membership.user.id),
            invitation_token=str(admin_membership.invitation_token),
            org_name=org.name,
        )

    return {"message": f"Organization '{org.name}' approved. Activation email sent."}


# ── Reject ──────────────────────────────────────────────────────────────


@router.post(
    "/organizations/{org_id}/reject",
    response={200: MessageSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Reject an organization",
)
def reject_organization(request: HttpRequest, org_id: UUID, payload: OrgRejectSchema):
    _ensure_superadmin(request)

    org = get_organization_by_id(org_id=org_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    org = org_services.reject_organization(
        organization=org, reviewed_by=request.auth, reason=payload.reason,
    )

    # Send rejection email
    admin_membership = Membership.objects.filter(
        organization=org, role=Role.ORG_ADMIN
    ).select_related("user").first()

    if admin_membership:
        from src.apps.emails.tasks import send_rejection_email

        send_rejection_email.delay(
            user_id=str(admin_membership.user.id),
            org_name=org.name,
            reason=payload.reason,
        )

    return {"message": f"Organization '{org.name}' rejected."}


# ── Suspend ─────────────────────────────────────────────────────────────


@router.post(
    "/organizations/{org_id}/suspend",
    response={200: MessageSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Suspend an organization",
)
def suspend_organization(request: HttpRequest, org_id: UUID, payload: OrgSuspendSchema):
    _ensure_superadmin(request)

    org = get_organization_by_id(org_id=org_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    org = org_services.suspend_organization(organization=org, reviewed_by=request.auth)

    return {"message": f"Organization '{org.name}' suspended."}