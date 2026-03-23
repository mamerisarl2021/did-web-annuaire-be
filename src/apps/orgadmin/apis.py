"""
Org Admin API endpoints.

All endpoints require JWT auth and an active membership in the target org.
"""

from typing import Optional
from uuid import UUID

from django.http import HttpRequest
from ninja import Router
from ninja_jwt.authentication import JWTAuth

from src.apps.organizations.models import Membership, Organization
from src.apps.organizations.selectors import (
    get_organization_by_id,
    get_organization_members,
    get_organization_stats,
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
    UpdateMemberSchema,
    UpdateOrgSchema,
)
from src.common.exceptions import NotFoundError, ValidationError
from src.common.pagination import PaginatedResponse, paginate_queryset
from src.common.permissions import Permission, require_permission
from src.common.types import MembershipStatus, Role

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
    response=PaginatedResponse,
    auth=JWTAuth(),
    summary="List my organizations",
)
def list_my_organizations(
    request: HttpRequest,
    page: int = 1,
    page_size: int = 25,
):
    """Return all organizations the current user is an active member of."""
    qs = get_user_organizations(user=request.auth)
    sliced_qs, total = paginate_queryset(
        queryset=qs,
        page=page,
        page_size=page_size,
        max_page_size=100,
    )
    return {
        "count": total,
        "results": [_org_summary(org) for org in sliced_qs],
    }


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

    stats = get_organization_stats(organization_id=org_id)

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
        "member_count": stats["total_members"],
        "document_count": stats["total_documents"],
        "certificate_count": stats["total_certificates"],
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

    stats = get_organization_stats(organization_id=org_id)

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
        "member_count": stats["total_members"],
        "document_count": stats["total_documents"],
        "certificate_count": stats["total_certificates"],
    }


# ── Org stats ────────────────────────────────────────────────────────────


@router.get(
    "/organizations/{org_id}/stats",
    response={200: OrgStatsSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Get organization stats — use ?scope=me to get current-user counts only",
)
def organization_stats(
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

    stats = get_organization_stats(
        organization_id=org_id,
        user_id=request.auth.id if scope == "me" else None,
    )

    return {
        **stats,
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
    # import circulaire avec audits — intentionnel
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
    response=PaginatedResponse,
    auth=JWTAuth(),
    summary="List organization members (ORG_ADMIN only)",
)
def list_members(
    request: HttpRequest,
    org_id: UUID,
    page: int = 1,
    page_size: int = 25,
):
    """Only ORG_ADMINs (MANAGE_MEMBERS permission) can list members."""
    require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)

    qs = get_organization_members(organization_id=org_id)
    sliced_qs, total = paginate_queryset(
        queryset=qs,
        page=page,
        page_size=page_size,
        max_page_size=100,
    )
    return {
        "count": total,
        "results": [_member_dict(m) for m in sliced_qs],
    }


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

    # Délègue la mise à jour du profil et l'accès audit au service
    new_membership = org_services.update_member_profile(
        membership=new_membership,
        updated_by=request.auth,
        full_name=payload.full_name if payload.full_name and not new_membership.user.full_name else None,
        phone=payload.phone or None,
        functions=payload.functions or None,
        has_audit_access=payload.has_audit_access if payload.has_audit_access else None,
    )

    # import circulaire avec emails.tasks — intentionnel
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

    # Empêche de changer son propre rôle
    if target.user_id == request.auth.id:
        raise ValidationError("You cannot change your own role.")

    try:
        new_role = Role(payload.role)
    except ValueError:
        raise ValidationError(f"Invalid role: {payload.role}")

    # La garde 'unique admin' est maintenant dans le service
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

    # La garde 'unique admin' est maintenant dans le service
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
        .select_related("user", "organization")
        .first()
    )

    if target is None:
        raise NotFoundError("Membership not found.")

    # La validation et l'audit sont encapsulés dans le service
    target = org_services.reactivate_membership(
        membership=target, reactivated_by=request.auth
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
        .select_related("user", "organization")
        .first()
    )

    if target_membership is None:
        raise NotFoundError("Membership not found.")

    # La mise à jour de l'utilisateur et l'audit sont délégués au service
    target_membership = org_services.update_member_profile(
        membership=target_membership,
        updated_by=request.auth,
        full_name=payload.full_name,
        phone=payload.phone,
        functions=payload.functions,
        has_audit_access=payload.has_audit_access,
    )

    return _member_dict(target_membership)