"""
Org Admin API endpoints.

All endpoints require JWT auth and an active membership in the target org.
Permission checks use the RBAC system from common/permissions.py.
"""

from uuid import UUID

from django.db import transaction
from django.http import HttpRequest
from ninja import Router
from ninja_jwt.authentication import JWTAuth

from src.apps.certificates.models import Certificate
from src.apps.documents.models import DIDDocument
from src.apps.organizations.models import Membership, Organization
from src.apps.organizations.selectors import (
    get_active_membership,
    get_organization_by_id,
    get_organization_members,
    get_user_organizations,
)
from src.apps.organizations import services as org_services
from src.apps.orgadmin.schemas import (
    ChangeMemberRoleSchema,
    ErrorSchema,
    InviteMemberSchema,
    MemberSchema,
    MessageSchema,
    OrgDetailSchema,
    OrgStatsSchema,
    OrgSummarySchema,
)
from src.common.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from src.common.permissions import Permission, require_permission
from src.common.types import MembershipStatus, Role

router = Router(tags=["Organization Admin"])


# ── Helpers ──────────────────────────────────────────────────────────────


def _org_summary(org: Organization) -> dict:
    member_count = Membership.objects.filter(organization=org).exclude(
        status=MembershipStatus.DEACTIVATED
    ).count()
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "type": org.type,
        "status": org.status,
        "member_count": member_count,
        "document_count": DIDDocument.objects.filter(organization_id=org.id ).count(),
        "certificate_count": Certificate.objects.filter(organization_id=org.id).count(),
    }


def _member_dict(m: Membership) -> dict:
    return {
        "id": m.id,
        "user_id": m.user.id,
        "email": m.user.email,
        "full_name": m.user.full_name,
        "phone": m.user.phone,
        "functions": m.user.functions,
        "role": m.role,
        "status": m.status,
        "is_active": m.user.is_active,
        "invited_by_email": m.invited_by.email if m.invited_by else None,
        "activated_at": m.activated_at.isoformat() if m.activated_at else None,
        "created_at": m.created_at.isoformat(),
    }


# ── My organizations ────────────────────────────────────────────────────


@router.get(
    "/organizations",
    response=list[OrgSummarySchema],
    auth=JWTAuth(),
    summary="List my organizations",
)
def list_my_organizations(request: HttpRequest):
    """Return all organizations the current user is an active member of."""
    orgs = get_user_organizations(user=request.auth)
    return [_org_summary(org) for org in orgs]


# ── Org detail ───────────────────────────────────────────────────────────


@router.get(
    "/organizations/{org_id}",
    response={200: OrgDetailSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Get organization detail",
)
def get_organization_detail(request: HttpRequest, org_id: UUID):
    """Get details of an organization (requires VIEW_DOCUMENTS permission)."""
    require_permission(request.auth, org_id, Permission.VIEW_DOCUMENTS)

    org = get_organization_by_id(org_id=org_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    member_count = Membership.objects.filter(organization=org).exclude(
        status=MembershipStatus.DEACTIVATED
    ).count()

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
        "created_at": org.created_at.isoformat(),
        "member_count": member_count,
        "document_count": 0,
        "certificate_count": 0,
    }


# ── Org stats ────────────────────────────────────────────────────────────


@router.get(
    "/organizations/{org_id}/stats",
    response={200: OrgStatsSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Get organization stats",
)
def get_organization_stats(request: HttpRequest, org_id: UUID):
    require_permission(request.auth, org_id, Permission.VIEW_DOCUMENTS)

    members = Membership.objects.filter(organization_id=org_id)

    return {
        "total_members": members.exclude(status=MembershipStatus.DEACTIVATED).count(),
        "active_members": members.filter(status=MembershipStatus.ACTIVE).count(),
        "invited_members": members.filter(status=MembershipStatus.INVITED).count(),
        "total_documents": 0,
        "total_certificates": 0,
    }


# ── Members list ─────────────────────────────────────────────────────────


@router.get(
    "/organizations/{org_id}/members",
    response=list[MemberSchema],
    auth=JWTAuth(),
    summary="List organization members",
)
def list_members(request: HttpRequest, org_id: UUID):
    require_permission(request.auth, org_id, Permission.VIEW_DOCUMENTS)

    members = get_organization_members(organization_id=org_id)
    return [_member_dict(m) for m in members]


# ── Invite member ────────────────────────────────────────────────────────


@router.post(
    "/organizations/{org_id}/members/invite",
    response={201: MemberSchema, 400: ErrorSchema, 409: ErrorSchema},
    auth=JWTAuth(),
    summary="Invite a member to the organization",
)
def invite_member(request: HttpRequest, org_id: UUID, payload: InviteMemberSchema):
    membership = require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)
    org = membership.organization

    # Validate role
    try:
        role = Role(payload.role)
    except ValueError:
        raise ValidationError(f"Invalid role: {payload.role}. Use ORG_MEMBER or AUDITOR.")

    new_membership = org_services.invite_member(
        organization=org,
        email=payload.email,
        role=role,
        invited_by=request.auth,
    )

    # If full_name was provided and user has no name yet, set it
    if payload.full_name and not new_membership.user.full_name:
        from src.apps.users.services import update_user_profile
        update_user_profile(user=new_membership.user, full_name=payload.full_name)
        new_membership.user.refresh_from_db()

    from src.apps.emails.tasks import send_member_invitation_email
    send_member_invitation_email.delay(
        user_id=str(new_membership.user.id),
        invitation_token=str(new_membership.invitation_token),
        org_name=org.name,
        role=payload.role,
        invited_by_name=request.auth.full_name or request.auth.email,
    )

    return 201, _member_dict(new_membership)


# ── Change member role ───────────────────────────────────────────────────


@router.put(
    "/organizations/{org_id}/members/{membership_id}/role",
    response={200: MemberSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Change a member's role",
)
def change_member_role(
    request: HttpRequest,
    org_id: UUID,
    membership_id: UUID,
    payload: ChangeMemberRoleSchema,
):
    require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)

    target = Membership.objects.filter(
        id=membership_id, organization_id=org_id
    ).select_related("user", "invited_by").first()

    if target is None:
        raise NotFoundError("Membership not found.")

    # Prevent changing own role
    if target.user_id == request.auth.id:
        raise ValidationError("You cannot change your own role.")

    # Prevent demoting the only ORG_ADMIN
    if target.role == Role.ORG_ADMIN:
        admin_count = Membership.objects.filter(
            organization_id=org_id, role=Role.ORG_ADMIN
        ).exclude(status=MembershipStatus.DEACTIVATED).count()
        if admin_count <= 1:
            raise ValidationError("Cannot change role of the only organization admin.")

    try:
        new_role = Role(payload.role)
    except ValueError:
        raise ValidationError(f"Invalid role: {payload.role}")

    target = org_services.change_member_role(
        membership=target, new_role=new_role, changed_by=request.auth,
    )
    target.refresh_from_db()

    return _member_dict(
        Membership.objects.filter(id=target.id).select_related("user", "invited_by").first()
    )


# ── Deactivate member ───────────────────────────────────────────────────


@router.post(
    "/organizations/{org_id}/members/{membership_id}/deactivate",
    response={200: MessageSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Deactivate a member",
)
def deactivate_member(request: HttpRequest, org_id: UUID, membership_id: UUID):
    require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)

    target = Membership.objects.filter(
        id=membership_id, organization_id=org_id
    ).select_related("user").first()

    if target is None:
        raise NotFoundError("Membership not found.")

    if target.user_id == request.auth.id:
        raise ValidationError("You cannot deactivate yourself.")

    if target.role == Role.ORG_ADMIN:
        admin_count = Membership.objects.filter(
            organization_id=org_id, role=Role.ORG_ADMIN
        ).exclude(status=MembershipStatus.DEACTIVATED).count()
        if admin_count <= 1:
            raise ValidationError("Cannot deactivate the only organization admin.")

    org_services.deactivate_membership(membership=target, deactivated_by=request.auth)

    return {"message": f"Member {target.user.email} has been deactivated."}
