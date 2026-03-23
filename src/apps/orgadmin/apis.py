"""
Org Admin API endpoints.

All endpoints require JWT auth and an active membership in the target org.
"""

from typing import Optional
from uuid import UUID

from django.http import HttpRequest
from ninja import Router
from ninja_jwt.authentication import JWTAuth

from src.apps.certificates.models import Certificate
from src.apps.documents.models import DIDDocument, DocumentStatus
from src.apps.organizations.models import Membership, Organization
from src.apps.organizations.selectors import (
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
    UpdateMemberSchema,
    UpdateOrgSchema,
)
from src.common.exceptions import NotFoundError, ValidationError
from src.common.pagination import PaginatedResponse, paginate_queryset
from src.common.permissions import Permission, require_permission
from src.common.types import MembershipStatus, Role, AuditAction
from src.apps.audits import services as audit_services

router = Router(tags=["Organization Admin"])


# ── Helpers ──────────────────────────────────────────────────────────────


def _org_summary(org: Organization) -> dict:
    member_count = (
        Membership.objects.filter(organization=org)
        .exclude(status=MembershipStatus.DEACTIVATED)
        .count()
    )
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "type": org.type,
        "status": org.status,
        "member_count": member_count,
        "document_count": DIDDocument.objects.filter(organization_id=org.id).count(),
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

    member_count = (
        Membership.objects.filter(organization=org)
        .exclude(status=MembershipStatus.DEACTIVATED)
        .count()
    )

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
        "document_count": DIDDocument.objects.filter(organization_id=org.id).count(),
        "certificate_count": Certificate.objects.filter(organization_id=org.id).count(),
    }


@router.patch(
    "/organizations/{org_id}",
    response={200: OrgDetailSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Update organization details",
)
def update_organization(
    request: HttpRequest,
    org_id: UUID,
    payload: UpdateOrgSchema,
):
    """Update organization information (requires ORG_ADMIN via MANAGE_MEMBERS generic)."""
    # Assuming MANAGE_MEMBERS is equivalent to ORG_ADMIN role for updates here.
    require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)

    org = get_organization_by_id(org_id=org_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    org = org_services.update_organization(
        organization=org,
        actor=request.auth,
        name=payload.name,
        type=payload.type,
        email=payload.email,
        country=payload.country,
        address=payload.address,
        description=payload.description,
    )

    member_count = (
        Membership.objects.filter(organization=org)
        .exclude(status=MembershipStatus.DEACTIVATED)
        .count()
    )

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
        "document_count": DIDDocument.objects.filter(organization_id=org.id).count(),
        "certificate_count": Certificate.objects.filter(organization_id=org.id).count(),
    }


# ── Org stats ────────────────────────────────────────────────────────────


@router.get(
    "/organizations/{org_id}/stats",
    response={200: OrgStatsSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Get organization stats — use ?scope=me to get current-user counts only",
)
def get_organization_stats(
    request: HttpRequest,
    org_id: UUID,
    scope: Optional[str] = None,
):
    """
    Returns org-wide statistics by default.
    When `?scope=me` is passed the counts are filtered to the requesting user:
    - `total_documents` / `total_certificates` reflect only that user's items.
    - Member counts are omitted (set to 0) in the me-scoped response.
    """
    membership = require_permission(request.auth, org_id, Permission.VIEW_DOCUMENTS)

    if scope == "me":
        user = request.auth
        my_docs = DIDDocument.objects.filter(organization_id=org_id, owner=user)
        return {
            "total_members": 0,
            "active_members": 0,
            "invited_members": 0,
            "total_documents": my_docs.count(),
            "draft_documents": my_docs.filter(status=DocumentStatus.DRAFT).count(),
            "signed_documents": my_docs.filter(status__in=[DocumentStatus.SIGNED, DocumentStatus.PUBLISHED]).count(),
            "published_documents": my_docs.filter(
                status=DocumentStatus.PUBLISHED
            ).count(),
            "total_certificates": Certificate.objects.filter(
                organization_id=org_id, created_by=user
            ).count(),
            "my_role": membership.role,
            "can_view_audits": membership.can_view_audits,
        }

    members = Membership.objects.filter(organization_id=org_id)
    org_docs = DIDDocument.objects.filter(organization_id=org_id)

    return {
        "total_members": members.exclude(status=MembershipStatus.DEACTIVATED).count(),
        "active_members": members.filter(status=MembershipStatus.ACTIVE).count(),
        "invited_members": members.filter(status=MembershipStatus.INVITED).count(),
        "total_documents": org_docs.count(),
        "draft_documents": org_docs.filter(status=DocumentStatus.DRAFT).count(),
        "signed_documents": org_docs.filter(status__in=[DocumentStatus.SIGNED, DocumentStatus.PUBLISHED]).count(),
        "published_documents": org_docs.filter(status=DocumentStatus.PUBLISHED).count(),
        "total_certificates": Certificate.objects.filter(
            organization_id=org_id
        ).count(),
        "my_role": membership.role,
        "can_view_audits": membership.can_view_audits,
    }


def _audit_dict(a) -> dict:
    return {
        "id": a.id,
        "action": a.action,
        "resource_type": a.resource_type,
        "resource_id": a.resource_id,
        "description": a.description,
        "metadata": a.metadata,
        "actor_email": a.actor_email,
        "created_at": a.created_at.isoformat(),
        "ip_address": a.ip_address,
    }


@router.get(
    "/organizations/{org_id}/audits",
    response=PaginatedResponse,
    auth=JWTAuth(),
    summary="List organization audits",
)
def list_audits(
    request,
    org_id: UUID,
    page: int = 1,
    page_size: int = 25,
):
    """
    List audit logs for the organization.
    Requires VIEW_AUDITS permission (built into ORG_ADMIN, or via has_audit_access).
    """
    require_permission(request.auth, org_id, Permission.VIEW_AUDITS)

    from src.apps.audits.models import AuditLog

    qs = AuditLog.objects.filter(organization_id=org_id).order_by("-created_at")
    sliced_qs, total = paginate_queryset(
        queryset=qs,
        page=page,
        page_size=page_size,
        max_page_size=100,
    )

    return {
        "count": total,
        "results": [_audit_dict(a) for a in sliced_qs],
    }


# ── Members list ─────────────────────────────────────────────────────────


@router.get(
    "/organizations/{org_id}/members",
    response=list[MemberSchema],
    auth=JWTAuth(),
    summary="List organization members (ORG_ADMIN only)",
)
def list_members(request: HttpRequest, org_id: UUID):
    """Only ORG_ADMINs (MANAGE_MEMBERS permission) can list members."""
    require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)

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

    new_membership = org_services.invite_member(
        organization=org,
        email=payload.email,
        role=Role.ORG_MEMBER,
        invited_by=request.auth,
    )

    # Apply optional profile fields to the created user
    profile_updates = {}
    if payload.full_name and not new_membership.user.full_name:
        profile_updates["full_name"] = payload.full_name
    if payload.phone:
        profile_updates["phone"] = payload.phone
    if payload.functions:
        profile_updates["functions"] = payload.functions

    if profile_updates:
        from src.apps.users.services import update_user_profile

        update_user_profile(user=new_membership.user, **profile_updates)
        new_membership.user.refresh_from_db()

    # Apply has_audit_access directly on the membership
    if payload.has_audit_access:
        new_membership.has_audit_access = True
        new_membership.save(update_fields=["has_audit_access"])

    from src.apps.emails.tasks import send_member_invitation_email

    send_member_invitation_email.delay(
        user_id=str(new_membership.user.id),
        invitation_token=str(new_membership.invitation_token),
        org_name=org.name,
        role="ORG_MEMBER",
        invited_by_name=request.auth.full_name or request.auth.email,
    )

    return 201, _member_dict(
        Membership.objects.filter(id=new_membership.id)
        .select_related("user", "invited_by")
        .first()
    )


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

    target = (
        Membership.objects.filter(id=membership_id, organization_id=org_id)
        .select_related("user", "invited_by")
        .first()
    )

    if target is None:
        raise NotFoundError("Membership not found.")

    # Prevent changing own role
    if target.user_id == request.auth.id:
        raise ValidationError("You cannot change your own role.")

    # Prevent demoting the only ORG_ADMIN
    if target.role == Role.ORG_ADMIN:
        admin_count = (
            Membership.objects.filter(organization_id=org_id, role=Role.ORG_ADMIN)
            .exclude(status=MembershipStatus.DEACTIVATED)
            .count()
        )
        if admin_count <= 1:
            raise ValidationError("Cannot change role of the only organization admin.")

    try:
        new_role = Role(payload.role)
    except ValueError:
        raise ValidationError(f"Invalid role: {payload.role}")

    target = org_services.change_member_role(
        membership=target,
        new_role=new_role,
        changed_by=request.auth,
    )
    target.refresh_from_db()

    return _member_dict(
        Membership.objects.filter(id=target.id)
        .select_related("user", "invited_by")
        .first()
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

    target = (
        Membership.objects.filter(id=membership_id, organization_id=org_id)
        .select_related("user")
        .first()
    )

    if target is None:
        raise NotFoundError("Membership not found.")

    if target.user_id == request.auth.id:
        raise ValidationError("You cannot deactivate yourself.")

    if target.role == Role.ORG_ADMIN:
        admin_count = (
            Membership.objects.filter(organization_id=org_id, role=Role.ORG_ADMIN)
            .exclude(status=MembershipStatus.DEACTIVATED)
            .count()
        )
        if admin_count <= 1:
            raise ValidationError("Cannot deactivate the only organization admin.")

    org_services.deactivate_membership(membership=target, deactivated_by=request.auth)

    return {"message": f"Member {target.user.email} has been deactivated."}


# ── Cancel invitation ───────────────────────────────────────────────────


@router.post(
    "/organizations/{org_id}/members/{membership_id}/cancel",
    response={200: MessageSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Cancel a pending member invitation",
)
def cancel_invitation(request: HttpRequest, org_id: UUID, membership_id: UUID):
    require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)

    target = (
        Membership.objects.filter(id=membership_id, organization_id=org_id)
        .select_related("user")
        .first()
    )

    if target is None:
        raise NotFoundError("Membership not found.")

    if target.status != MembershipStatus.INVITED:
        raise ValidationError("Only pending invitations can be canceled.")

    org_services.cancel_membership_invitation(
        membership=target, canceled_by=request.auth
    )

    return {"message": f"Invitation for {target.user.email} has been canceled."}


# ── Reactivate member ───────────────────────────────────────────────────


@router.post(
    "/organizations/{org_id}/members/{membership_id}/reactivate",
    response={200: MemberSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Reactivate a member",
)
def reactivate_member(request: HttpRequest, org_id: UUID, membership_id: UUID):
    require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)

    target = (
        Membership.objects.filter(id=membership_id, organization_id=org_id)
        .select_related("user")
        .first()
    )

    if target is None:
        raise NotFoundError("Membership not found.")

    if target.status != MembershipStatus.DEACTIVATED:
        raise ValidationError("Only deactivated members can be reactivated.")

    target.status = MembershipStatus.ACTIVE
    target.save(update_fields=["status", "updated_at"])

    audit_services.log_action(
        actor=request.auth,
        action=AuditAction.MEMBER_ACTIVATED,
        resource_type="MEMBERSHIP",
        resource_id=target.id,
        organization=target.organization,
        description=f"Member '{target.user.email}' reactivated manually.",
        metadata={"old_status": "DEACTIVATED", "new_status": "ACTIVE"},
    )

    return _member_dict(target)


# ── Update member ───────────────────────────────────────────────────────


@router.patch(
    "/organizations/{org_id}/members/{membership_id}",
    response={200: MemberSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Update a member's profile and audit access",
)
def update_member(
    request: HttpRequest,
    org_id: UUID,
    membership_id: UUID,
    payload: UpdateMemberSchema,
):
    require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)

    target_membership = (
        Membership.objects.filter(id=membership_id, organization_id=org_id)
        .select_related("user")
        .first()
    )

    if target_membership is None:
        raise NotFoundError("Membership not found.")

    user = target_membership.user
    update_user = False

    if payload.full_name is not None:
        user.full_name = payload.full_name
        update_user = True
    if payload.phone is not None:
        user.phone = payload.phone
        update_user = True
    if payload.functions is not None:
        user.functions = payload.functions
        update_user = True

    if update_user:
        user.save(update_fields=["full_name", "phone", "functions", "updated_at"])

    if (
        payload.has_audit_access is not None
        and target_membership.has_audit_access != payload.has_audit_access
    ):
        target_membership.has_audit_access = payload.has_audit_access
        target_membership.save(update_fields=["has_audit_access", "updated_at"])

    audit_services.log_action(
        actor=request.auth,
        action=AuditAction.MEMBER_ROLE_CHANGED,
        resource_type="MEMBERSHIP",
        resource_id=target_membership.id,
        organization=target_membership.organization,
        description=f"Member '{target_membership.user.email}' details updated.",
        metadata={"fields_updated": True},
    )

    return _member_dict(target_membership)