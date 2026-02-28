"""
DID Document API endpoints.

Mounted at: /api/v2/org/   (alongside orgadmin and cert routers)
Full paths:  /api/v2/org/organizations/{org_id}/documents/...

Scoping:
  - ORG_ADMIN:  sees all, reviews others', publishes directly from DRAFT
  - ORG_MEMBER: sees/edits own, submits for review, publishes/deactivates own
  - AUDITOR:    sees all (read-only)

Lifecycle:
  ORG_MEMBER: DRAFT → PENDING_REVIEW → APPROVED → PUBLISHED → DEACTIVATED
  ORG_ADMIN:  DRAFT → PUBLISHED (direct, skips review)
"""

from uuid import UUID

from django.http import HttpRequest
from ninja import Router
from ninja_jwt.authentication import JWTAuth

from src.apps.documents import selectors as doc_selectors
from src.apps.documents import services as doc_services
from src.apps.documents.assembler import build_did_uri
from src.apps.documents.models import DocumentVerificationMethod
from src.apps.documents.schemas import (
    AddVerificationMethodSchema,
    CreateDocumentSchema,
    DeactivateSchema,
    DocDetailSchema,
    DocListItemSchema,
    DocVersionSchema,
    ErrorSchema,
    MessageSchema,
    ReviewSchema,
    UpdateDraftSchema,
    VerificationMethodResponse,
)
from src.common.exceptions import NotFoundError, PermissionDeniedError
from src.common.permissions import Permission, require_permission
from src.common.types import Role

router = Router(tags=["DID Documents"])

_P = "/organizations/{org_id}/documents"


# ── Scoping helpers ──────────────────────────────────────────────────────


def _can_view_all(membership) -> bool:
    return membership.role in (Role.ORG_ADMIN, Role.AUDITOR)


def _is_admin(membership) -> bool:
    return membership.role == Role.ORG_ADMIN


def _require_doc_owner(doc, user, membership, action="access"):
    if doc.owner_id == user.id:
        return
    raise PermissionDeniedError(f"Only the document owner can {action} this document.")


def _require_owner_or_admin(doc, user, membership, action="access"):
    if doc.owner_id == user.id:
        return
    if membership.role == Role.ORG_ADMIN:
        return
    raise PermissionDeniedError(f"Only the document owner or an admin can {action} this document.")


def _require_reviewer(doc, user, membership):
    if membership.role != Role.ORG_ADMIN:
        raise PermissionDeniedError("Only organization admins can review documents.")
    if doc.owner_id == user.id:
        raise PermissionDeniedError("You cannot review your own document.")


# ── Serialization helpers ────────────────────────────────────────────────


def _did_uri(doc) -> str:
    return build_did_uri(
        org_slug=doc.organization.slug,
        owner_identifier=doc.owner_identifier,
        label=doc.label,
    )


def _vm_response(vm: DocumentVerificationMethod) -> dict:
    cv = vm.certificate.current_version
    return {
        "id": vm.id,
        "certificate_id": vm.certificate_id,
        "certificate_label": vm.certificate.label,
        "method_id_fragment": vm.method_id_fragment,
        "method_type": vm.method_type,
        "relationships": vm.relationship_list,
        "is_active": vm.is_active,
        "key_type": cv.key_type if cv else "",
        "key_curve": cv.key_curve if cv else "",
    }


def _doc_list_item(doc) -> dict:
    return {
        "id": doc.id,
        "label": doc.label,
        "status": doc.status,
        "did_uri": _did_uri(doc),
        "owner_email": doc.owner.email if doc.owner else "",
        "owner_identifier": doc.owner_identifier,
        "created_by_email": doc.created_by.email if doc.created_by else "",
        "vm_count": doc.verification_methods.filter(is_active=True).count(),
        "current_version_number": (
            doc.current_version.version_number if doc.current_version else None
        ),
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }


def _doc_detail(doc) -> dict:
    vms = doc_selectors.get_document_verification_methods(document_id=doc.id)

    # Build VC for published docs
    vc = doc_services.get_verifiable_credential(doc)

    return {
        "id": doc.id,
        "label": doc.label,
        "status": doc.status,
        "did_uri": _did_uri(doc),
        "owner_email": doc.owner.email if doc.owner else "",
        "owner_identifier": doc.owner_identifier,
        "owner_id": doc.owner_id,
        "draft_content": doc.draft_content,
        "content": doc.content,
        "created_by_email": doc.created_by.email if doc.created_by else "",
        "created_by_id": doc.created_by_id,
        "submitted_by_email": doc.submitted_by.email if doc.submitted_by else None,
        "submitted_at": doc.submitted_at.isoformat() if doc.submitted_at else None,
        "reviewed_by_email": doc.reviewed_by.email if doc.reviewed_by else None,
        "reviewed_at": doc.reviewed_at.isoformat() if doc.reviewed_at else None,
        "review_comment": doc.review_comment or "",
        "current_version_number": (
            doc.current_version.version_number if doc.current_version else None
        ),
        "verification_methods": [_vm_response(vm) for vm in vms],
        "verifiable_credential": vc,
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }


def _version_response(v) -> dict:
    return {
        "id": v.id,
        "version_number": v.version_number,
        "content": v.content,
        "signature": v.signature,
        "published_at": v.published_at.isoformat() if v.published_at else None,
        "published_by_email": v.published_by.email if v.published_by else "",
    }


def _get_doc_or_404(doc_id: UUID, org_id: UUID):
    doc = doc_selectors.get_document_by_id(doc_id=doc_id)
    if doc is None or str(doc.organization_id) != str(org_id):
        raise NotFoundError("Document not found.")
    return doc


# ═════════════════════════════════════════════════════════════════════════
# IMPORTANT: literal paths (pending-review) BEFORE parameterized ({doc_id})
# ═════════════════════════════════════════════════════════════════════════


# ── List documents ───────────────────────────────────────────────────────


@router.get(
    f"{_P}",
    response=list[DocListItemSchema],
    auth=JWTAuth(),
    summary="List DID documents (scoped by role)",
)
def list_documents(request: HttpRequest, org_id: UUID):
    membership = require_permission(request.auth, org_id, Permission.VIEW_DOCUMENTS)

    if _can_view_all(membership):
        docs = doc_selectors.get_org_documents(organization_id=org_id)
    else:
        docs = doc_selectors.get_user_documents(
            organization_id=org_id, user_id=request.auth.id,
        )

    return [_doc_list_item(d) for d in docs]


# ── Create document ──────────────────────────────────────────────────────


@router.post(
    f"{_P}",
    response={201: DocDetailSchema, 400: ErrorSchema, 409: ErrorSchema},
    auth=JWTAuth(),
    summary="Create a new DID document (DRAFT)",
)
def create_document(request: HttpRequest, org_id: UUID, payload: CreateDocumentSchema):
    membership = require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)

    vm_specs = [vm.dict() for vm in payload.verification_methods]
    svc_specs = (
        [s.dict() for s in payload.service_endpoints]
        if payload.service_endpoints else None
    )

    doc = doc_services.create_document(
        organization=membership.organization,
        label=payload.label,
        created_by=request.auth,
        verification_methods=vm_specs if vm_specs else None,
        service_endpoints=svc_specs,
    )

    doc = doc_selectors.get_document_by_id(doc_id=doc.id)
    return 201, _doc_detail(doc)


# ── Pending review (literal path — MUST be before {doc_id}) ─────────────


@router.get(
    f"{_P}/pending-review",
    response=list[DocListItemSchema],
    auth=JWTAuth(),
    summary="List documents pending review (ORG_ADMIN only)",
)
def list_pending_review(request: HttpRequest, org_id: UUID):
    require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)
    docs = doc_selectors.get_pending_review_documents(organization_id=org_id)
    return [_doc_list_item(d) for d in docs]


# ── Document detail ──────────────────────────────────────────────────────


@router.get(
    f"{_P}/{{doc_id}}",
    response={200: DocDetailSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Get DID document detail",
)
def get_document(request: HttpRequest, org_id: UUID, doc_id: UUID):
    membership = require_permission(request.auth, org_id, Permission.VIEW_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)

    if not _can_view_all(membership) and doc.owner_id != request.auth.id:
        raise NotFoundError("Document not found.")

    return _doc_detail(doc)


# ── Update draft ─────────────────────────────────────────────────────────


@router.patch(
    f"{_P}/{{doc_id}}/draft",
    response={200: DocDetailSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Update document draft",
)
def update_draft(
    request: HttpRequest, org_id: UUID, doc_id: UUID, payload: UpdateDraftSchema,
):
    membership = require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)
    _require_doc_owner(doc, request.auth, membership, action="edit")

    vm_specs = (
        [vm.dict() for vm in payload.verification_methods]
        if payload.verification_methods is not None else None
    )
    svc_specs = (
        [s.dict() for s in payload.service_endpoints]
        if payload.service_endpoints is not None else None
    )

    doc = doc_services.update_draft(
        document=doc, updated_by=request.auth,
        verification_methods=vm_specs, service_endpoints=svc_specs,
    )

    doc = doc_selectors.get_document_by_id(doc_id=doc.id)
    return _doc_detail(doc)


# ── Add verification method ─────────────────────────────────────────────


@router.post(
    f"{_P}/{{doc_id}}/verification-methods",
    response={
        201: VerificationMethodResponse, 400: ErrorSchema,
        404: ErrorSchema, 409: ErrorSchema,
    },
    auth=JWTAuth(),
    summary="Add a verification method to a draft document",
)
def add_verification_method(
    request: HttpRequest, org_id: UUID, doc_id: UUID,
    payload: AddVerificationMethodSchema,
):
    membership = require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)
    _require_doc_owner(doc, request.auth, membership, action="edit")

    vm = doc_services.add_verification_method(
        document=doc,
        certificate_id=payload.certificate_id,
        method_id_fragment=payload.method_id_fragment,
        relationships=payload.relationships,
        method_type=payload.method_type,
        added_by=request.auth,
    )

    vm = DocumentVerificationMethod.objects.select_related(
        "certificate", "certificate__current_version"
    ).get(id=vm.id)

    return 201, _vm_response(vm)


# ── Remove verification method ──────────────────────────────────────────


@router.delete(
    f"{_P}/{{doc_id}}/verification-methods/{{vm_id}}",
    response={200: MessageSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Remove a verification method from a draft document",
)
def remove_verification_method(
    request: HttpRequest, org_id: UUID, doc_id: UUID, vm_id: UUID,
):
    membership = require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)
    _require_doc_owner(doc, request.auth, membership, action="edit")

    doc_services.remove_verification_method(
        document=doc, vm_id=vm_id, removed_by=request.auth,
    )
    return {"message": "Verification method removed."}


# ── Submit for review (ORG_MEMBER only — admins publish directly) ──────


@router.post(
    f"{_P}/{{doc_id}}/submit",
    response={200: DocDetailSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Submit document for review (DRAFT → PENDING_REVIEW)",
)
def submit_for_review(request: HttpRequest, org_id: UUID, doc_id: UUID):
    membership = require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)
    _require_doc_owner(doc, request.auth, membership, action="submit")

    doc = doc_services.submit_for_review(document=doc, submitted_by=request.auth)

    doc = doc_selectors.get_document_by_id(doc_id=doc.id)
    return _doc_detail(doc)


# ── Approve ──────────────────────────────────────────────────────────────


@router.post(
    f"{_P}/{{doc_id}}/approve",
    response={200: DocDetailSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Approve document (PENDING_REVIEW → APPROVED)",
)
def approve_document(
    request: HttpRequest, org_id: UUID, doc_id: UUID, payload: ReviewSchema,
):
    membership = require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)
    doc = _get_doc_or_404(doc_id, org_id)
    _require_reviewer(doc, request.auth, membership)

    doc = doc_services.approve_document(
        document=doc, approved_by=request.auth, comment=payload.comment,
    )

    doc = doc_selectors.get_document_by_id(doc_id=doc.id)
    return _doc_detail(doc)


# ── Reject ───────────────────────────────────────────────────────────────


@router.post(
    f"{_P}/{{doc_id}}/reject",
    response={200: DocDetailSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Reject document (PENDING_REVIEW → REJECTED)",
)
def reject_document(
    request: HttpRequest, org_id: UUID, doc_id: UUID, payload: ReviewSchema,
):
    membership = require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)
    doc = _get_doc_or_404(doc_id, org_id)
    _require_reviewer(doc, request.auth, membership)

    doc = doc_services.reject_document(
        document=doc, rejected_by=request.auth, reason=payload.comment,
    )

    doc = doc_selectors.get_document_by_id(doc_id=doc.id)
    return _doc_detail(doc)


# ── Publish (sign + register) ───────────────────────────────────────────


@router.post(
    f"{_P}/{{doc_id}}/publish",
    response={200: DocDetailSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Sign and publish document",
)
def publish_document(request: HttpRequest, org_id: UUID, doc_id: UUID):
    """
    ORG_ADMIN: can publish from DRAFT (direct) or APPROVED
    ORG_MEMBER: can publish only from APPROVED (after review)
    """
    membership = require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)
    _require_owner_or_admin(doc, request.auth, membership, action="publish")

    # ORG_ADMIN can skip review and publish directly from DRAFT
    skip_review = _is_admin(membership) and doc.status == "DRAFT"

    doc = doc_services.sign_and_publish(
        document=doc, published_by=request.auth, skip_review=skip_review,
    )

    doc = doc_selectors.get_document_by_id(doc_id=doc.id)
    return _doc_detail(doc)


# ── Deactivate ───────────────────────────────────────────────────────────


@router.post(
    f"{_P}/{{doc_id}}/deactivate",
    response={200: MessageSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Deactivate a published document",
)
def deactivate_document(
    request: HttpRequest, org_id: UUID, doc_id: UUID, payload: DeactivateSchema,
):
    membership = require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)
    _require_owner_or_admin(doc, request.auth, membership, action="deactivate")

    doc_services.deactivate_document(
        document=doc, deactivated_by=request.auth, reason=payload.reason,
    )
    return {"message": f"Document '{doc.label}' has been deactivated."}


# ── Version history ──────────────────────────────────────────────────────


@router.get(
    f"{_P}/{{doc_id}}/versions",
    response=list[DocVersionSchema],
    auth=JWTAuth(),
    summary="List published versions of a document",
)
def list_versions(request: HttpRequest, org_id: UUID, doc_id: UUID):
    membership = require_permission(request.auth, org_id, Permission.VIEW_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)

    if not _can_view_all(membership) and doc.owner_id != request.auth.id:
        raise NotFoundError("Document not found.")

    versions = doc_selectors.get_document_versions(document_id=doc_id)
    return [_version_response(v) for v in versions]


# ── Public DID resolution (no auth) ─────────────────────────────────────


@router.get(
    f"{_P}/{{doc_id}}/did.json",
    response={200: dict, 404: ErrorSchema},
    summary="Resolve published DID document (public, no auth)",
)
def resolve_did_document(request: HttpRequest, org_id: UUID, doc_id: UUID):
    doc = doc_selectors.get_document_by_id(doc_id=doc_id)
    if doc is None or str(doc.organization_id) != str(org_id):
        raise NotFoundError("DID document not found.")
    if doc.status != "PUBLISHED" or not doc.content:
        raise NotFoundError("DID document not published.")
    return doc.content


# ── Verifiable Credential (no auth) ─────────────────────────────────────


@router.get(
    f"{_P}/{{doc_id}}/vc.json",
    response={200: dict, 404: ErrorSchema},
    summary="Get Verifiable Credential for a published document",
)
def get_verifiable_credential(request: HttpRequest, org_id: UUID, doc_id: UUID):
    doc = doc_selectors.get_document_by_id(doc_id=doc_id)
    if doc is None or str(doc.organization_id) != str(org_id):
        raise NotFoundError("Document not found.")

    vc = doc_services.get_verifiable_credential(doc)
    if vc is None:
        raise NotFoundError("Verifiable Credential not available. Document must be published.")
    return vc