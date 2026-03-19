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
)
from src.apps.organizations import services as org_services
from src.apps.superadmin.schemas import (
    DashboardStatsSchema,
    ErrorSchema,
    MessageSchema,
    OrgDetailSchema,
    OrgListItemSchema,
    OrgRejectSchema,
    OrgSuspendSchema,
    SAUserSchema,
    AddUserToOrgSchema,
    SAAuditLogSchema,
    SADIDDocumentSchema,
    SACertificateSchema,
)
from src.apps.users.models import User
from src.apps.documents.models import DIDDocument
from src.apps.certificates.models import Certificate
from src.apps.audits.models import AuditLog
from src.common.exceptions import NotFoundError
from src.common.permissions import require_superadmin
from src.common.types import OrgStatus, Role

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
        "pending_count": Organization.objects.filter(
            status=OrgStatus.PENDING_REVIEW
        ).count(),
        "approved_count": Organization.objects.filter(
            status=OrgStatus.APPROVED
        ).count(),
        "rejected_count": Organization.objects.filter(
            status=OrgStatus.REJECTED
        ).count(),
        "suspended_count": Organization.objects.filter(
            status=OrgStatus.SUSPENDED
        ).count(),
        "total_users": User.objects.count(),
        "active_users": User.objects.filter(is_active=True).count(),
        "total_did_documents": DIDDocument.objects.count(),
        "total_certificates": Certificate.objects.count(),
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
    status: str = Query(
        None,
        description="Filter by status: PENDING_REVIEW, APPROVED, REJECTED, SUSPENDED",
    ),
):
    _ensure_superadmin(request)

    qs = Organization.objects.select_related("created_by").order_by("-created_at")
    if status:
        qs = qs.filter(status=status)

    results = []
    for org in qs:
        # Get the org admin email
        admin_membership = (
            Membership.objects.filter(organization=org, role=Role.ORG_ADMIN)
            .select_related("user")
            .first()
        )

        results.append(
            {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "type": org.type,
                "country": org.country,
                "email": org.email,
                "status": org.status,
                "created_at": org.created_at.isoformat(),
                "admin_email": admin_membership.user.email
                if admin_membership
                else None,
            }
        )

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
        Organization.objects.select_related(
            "authorization_document",
            "justification_document",
            "created_by",
            "reviewed_by",
        )
        .filter(id=org_id)
        .first()
    )
    if org is None:
        raise NotFoundError("Organization not found.")

    # Get org admin
    admin_membership = (
        Membership.objects.filter(organization=org, role=Role.ORG_ADMIN)
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
    admin_membership = (
        Membership.objects.filter(organization=org, role=Role.ORG_ADMIN)
        .select_related("user")
        .first()
    )

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
        organization=org,
        reviewed_by=request.auth,
        reason=payload.reason,
    )

    # Send rejection email
    admin_membership = (
        Membership.objects.filter(organization=org, role=Role.ORG_ADMIN)
        .select_related("user")
        .first()
    )

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


# ── Delete ──────────────────────────────────────────────────────────────


@router.delete(
    "/organizations/{org_id}",
    response={200: MessageSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Delete an organization",
)
def delete_organization(request: HttpRequest, org_id: UUID):
    _ensure_superadmin(request)

    org = get_organization_by_id(org_id=org_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    org_name = org.name
    org_services.delete_organization(organization=org, deleted_by=request.auth)

# ── Users ───────────────────────────────────────────────────────────────


@router.get(
    "/users",
    response=list[SAUserSchema],
    auth=JWTAuth(),
    summary="List all users",
)
def list_users(request: HttpRequest):
    _ensure_superadmin(request)

    users = User.objects.prefetch_related(
        "memberships", "memberships__organization"
    ).order_by("-created_at")

    results = []
    for u in users:
        memberships_data = []
        for m in u.memberships.all():
            memberships_data.append({
                "id": m.id,
                "org_id": m.organization.id,
                "org_name": m.organization.name,
                "role": m.role,
                "status": m.status,
            })
        
        results.append({
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "phone": u.phone,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat(),
            "memberships": memberships_data,
        })

    return results


@router.delete(
    "/users/{user_id}",
    response={200: MessageSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Delete a user",
)
def delete_user(request: HttpRequest, user_id: UUID):
    _ensure_superadmin(request)
    
    from src.apps.users.services import delete_user as svc_delete_user
    u = User.objects.filter(id=user_id).first()
    if not u:
        raise NotFoundError("User not found.")
    
    email = u.email
    svc_delete_user(user=u, deleted_by=request.auth)
    return {"message": f"User '{email}' deleted."}


@router.post(
    "/users/{user_id}/add-to-org",
    response={200: MessageSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Add user to organization",
)
def add_user_to_org(request: HttpRequest, user_id: UUID, payload: AddUserToOrgSchema):
    _ensure_superadmin(request)
    u = User.objects.filter(id=user_id).first()
    if not u:
        raise NotFoundError("User not found.")
        
    org = get_organization_by_id(org_id=payload.org_id)
    if not org:
        raise NotFoundError("Organization not found.")
        
    # Check if membership already exists
    if Membership.objects.filter(user=u, organization=org).exists():
        return {"message": "User is already a member of this organization."}
        
    org_services.create_membership(
        user=u,
        organization=org,
        role=payload.role,
        status="ACTIVE",
        invited_by=request.auth
    )
    return {"message": f"User added to {org.name}."}


@router.post(
    "/users/{user_id}/cancel-invite/{org_id}",
    response={200: MessageSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Cancel a user's invite to an organization",
)
def cancel_invite(request: HttpRequest, user_id: UUID, org_id: UUID):
    _ensure_superadmin(request)
    m = Membership.objects.filter(user_id=user_id, organization_id=org_id, status="INVITED").first()
    if not m:
        raise NotFoundError("Invitation not found.")
        
    org_services.cancel_membership_invitation(membership=m, canceled_by=request.auth)
    return {"message": "Invitation canceled."}


# ── Audits ─────────────────────────────────────────────────────────────

@router.get(
    "/audits",
    response=list[SAAuditLogSchema],
    auth=JWTAuth(),
    summary="List audit logs",
)
def list_audits(request: HttpRequest):
    _ensure_superadmin(request)
    logs = AuditLog.objects.select_related("organization").order_by("-created_at")[:1000]

    return [
        {
            "id": log.id,
            "actor_email": log.actor_email,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "description": log.description,
            "created_at": log.created_at.isoformat(),
            "organization_name": log.organization.name if log.organization else None,
            "ip_address": log.ip_address,
            "user_agent": log.metadata.get("user_agent") if isinstance(log.metadata, dict) else None,
            "metadata": log.metadata,
        }
        for log in logs
    ]


# ── DID Documents ──────────────────────────────────────────────────────

@router.get(
    "/documents",
    response=list[SADIDDocumentSchema],
    auth=JWTAuth(),
    summary="List DID Documents",
)
def list_documents(request: HttpRequest):
    _ensure_superadmin(request)
    docs = DIDDocument.objects.select_related("organization", "owner").order_by("-created_at")
    
    return [
        {
            "id": doc.id,
            "label": doc.label,
            "organization_name": doc.organization.name,
            "org_slug": doc.organization.slug,
            "owner_email": doc.owner.email,
            "owner_identifier": doc.owner_identifier,
            "status": doc.status,
            "created_at": doc.created_at.isoformat(),
            "updated_at": doc.updated_at.isoformat(),
        }
        for doc in docs
    ]


@router.delete(
    "/documents/{doc_id}",
    response={200: MessageSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Delete or deactivate a DID Document",
)
def delete_document(request: HttpRequest, doc_id: UUID):
    _ensure_superadmin(request)
    doc = DIDDocument.objects.filter(id=doc_id).first()
    if not doc:
        raise NotFoundError("DID Document not found.")
        
    if doc.status == "PUBLISHED":
        from src.apps.documents.services import deactivate_document
        deactivate_document(document=doc, deactivated_by=request.auth, reason="Deactivated by Superadmin")
        return {"message": "Document deactivated successfully."}
    else:
        doc.delete()
        return {"message": "Document deleted successfully."}


# ── Certificates ───────────────────────────────────────────────────────

@router.get(
    "/certificates",
    response=list[SACertificateSchema],
    auth=JWTAuth(),
    summary="List Certificates",
)
def list_certificates(request: HttpRequest):
    _ensure_superadmin(request)
    certs = Certificate.objects.select_related("organization", "current_version").order_by("-created_at")
    
    return [
        {
            "id": c.id,
            "label": c.label,
            "organization_name": c.organization.name,
            "org_slug": c.organization.slug,
            "status": c.status,
            "created_at": c.created_at.isoformat(),
            "key_type": c.current_version.key_type if c.current_version else None,
            "not_valid_after": c.current_version.not_valid_after.isoformat() if c.current_version and c.current_version.not_valid_after else None,
        }
        for c in certs
    ]

@router.delete(
    "/certificates/{cert_id}",
    response={200: MessageSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Delete or revoke a Certificate",
)
def delete_certificate(request: HttpRequest, cert_id: UUID):
    _ensure_superadmin(request)
    cert = Certificate.objects.filter(id=cert_id).first()
    if not cert:
        raise NotFoundError("Certificate not found.")
        
    if cert.status == "ACTIVE":
        from src.apps.certificates.services import revoke_certificate
        revoke_certificate(certificate=cert, revoked_by=request.auth, reason="Revoked by Superadmin")
        return {"message": "Certificate revoked successfully."}
    else:
        cert.delete()
        return {"message": "Certificate deleted successfully."}
