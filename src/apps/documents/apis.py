"""
Points de terminaison de l'API Document DID.

Monté sous : /api/v2/org/   (aux côtés des routeurs orgadmin et cert)
Chemins complets :  /api/v2/org/organizations/{org_id}/documents/...

Portée :
  - ORG_ADMIN : voit tout, examine ceux des autres, publie directement depuis DRAFT
  - ORG_MEMBER : voit/modifie les siens, soumet pour examen, publie/désactive les siens
  - AUDITOR : voit tout (lecture seule)

Cycle de vie :
  ORG_MEMBER : DRAFT → PENDING_REVIEW → APPROVED → PUBLISHED → DEACTIVATED
  ORG_ADMIN :  DRAFT → PUBLISHED (direct, ignore l'examen)

Flux de mise à jour (pour les documents déjà PUBLISHED) :
  Le propriétaire modifie draft_content → re-publie (crée une nouvelle version).
  L'ORG_ADMIN peut également re-publier n'importe quel document.
"""

from uuid import UUID

from django.http import HttpRequest
from ninja import Router
from ninja_jwt.authentication import JWTAuth

from src.apps.certificates import selectors as cert_selectors
from src.apps.documents import selectors as doc_selectors
from src.apps.documents import services as doc_services
from src.apps.documents.models import DocumentVerificationMethod
from src.apps.documents.schemas import (
    AddVerificationMethodSchema,
    CreateDocumentSchema,
    DeactivateSchema,
    DocDetailSchema,
    ErrorSchema,
    MessageSchema,
    ReviewSchema,
    UpdateDraftSchema,
    VerificationMethodResponse,
)
from src.common.did.assembler import build_did_uri
from src.common.exceptions import NotFoundError
from src.common.pagination import PaginatedResponse, paginate_queryset
from src.common.permissions import (
    Permission,
    require_document_owner,
    require_document_owner_or_admin,
    require_document_reviewer,
    require_permission,
)
from src.common.types import Role

router = Router(tags=["DID Documents"])

_P = "/organizations/{org_id}/documents"


# ── Aides à la portée ───────────────────────────────────────────────────


def _can_view_all(membership) -> bool:
    return membership.role in (Role.ORG_ADMIN, Role.AUDITOR)


def _is_admin(membership) -> bool:
    return membership.role == Role.ORG_ADMIN


# ── Aides à la sérialisation ────────────────────────────────────────────


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
        "has_pending_draft": doc.has_pending_draft,
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }


def _doc_detail(doc) -> dict:
    vms = doc_selectors.get_document_verification_methods(document_id=doc.id)
    vc = doc_selectors.get_verifiable_credential(doc)

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
        "has_pending_draft": doc.has_pending_draft,
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
# IMPORTANT : chemins littéraux (pending-review) AVANT paramétré ({doc_id})
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    f"{_P}",
    response=PaginatedResponse,
    auth=JWTAuth(),
    summary="Liste des documents DID (portée par rôle)",
)
def list_documents(
    request: HttpRequest,
    org_id: UUID,
    page: int = 1,
    page_size: int = 25,
):
    membership = require_permission(request.auth, org_id, Permission.VIEW_DOCUMENTS)

    if _can_view_all(membership):
        qs = doc_selectors.get_org_documents(
            organization_id=org_id,
            user_id=request.auth.id,
        )
    else:
        qs = doc_selectors.get_user_documents(
            organization_id=org_id,
            user_id=request.auth.id,
        )

    sliced_qs, total = paginate_queryset(
        queryset=qs,
        page=page,
        page_size=page_size,
        max_page_size=100,
    )

    return {
        "count": total,
        "results": [_doc_list_item(d) for d in sliced_qs],
    }


@router.post(
    f"{_P}",
    response={201: DocDetailSchema, 400: ErrorSchema, 409: ErrorSchema},
    auth=JWTAuth(),
    summary="Créer un nouveau document DID (DRAFT)",
)
def create_document(request: HttpRequest, org_id: UUID, payload: CreateDocumentSchema):
    membership = require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)

    vm_specs = [vm.dict() for vm in payload.verification_methods]
    svc_specs = (
        [s.dict() for s in payload.service_endpoints]
        if payload.service_endpoints
        else None
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


@router.get(
    f"{_P}/pending-review",
    response=PaginatedResponse,
    auth=JWTAuth(),
    summary="Liste des documents en attente d'examen (ORG_ADMIN uniquement)",
)
def list_pending_review(
    request: HttpRequest,
    org_id: UUID,
    page: int = 1,
    page_size: int = 25,
):
    require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)
    qs = doc_selectors.get_pending_review_documents(organization_id=org_id)
    sliced_qs, total = paginate_queryset(
        queryset=qs,
        page=page,
        page_size=page_size,
        max_page_size=100,
    )
    return {
        "count": total,
        "results": [_doc_list_item(d) for d in sliced_qs],
    }


@router.get(
    f"{_P}/{{doc_id}}",
    response={200: DocDetailSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Obtenir les détails du document DID",
)
def get_document(request: HttpRequest, org_id: UUID, doc_id: UUID):
    membership = require_permission(request.auth, org_id, Permission.VIEW_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)

    if not _can_view_all(membership) and doc.owner_id != request.auth.id:
        raise NotFoundError("Document not found.")

    return _doc_detail(doc)


@router.patch(
    f"{_P}/{{doc_id}}/draft",
    response={200: DocDetailSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Mettre à jour le brouillon du document (DRAFT, REJECTED ou PUBLISHED)",
)
def update_draft(
    request: HttpRequest,
    org_id: UUID,
    doc_id: UUID,
    payload: UpdateDraftSchema,
):
    """
    Mettre à jour le contenu brouillon d'un document DID.

    Fonctionne sur les documents DRAFT, REJECTED et PUBLISHED :
    - DRAFT/REJECTED : édition normale avant (re-)soumission
    - PUBLISHED : crée un nouveau brouillon pour la prochaine version

    Seul le propriétaire du document peut modifier.
    """
    require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)
    require_document_owner(request.auth, doc)

    vm_specs = (
        [vm.dict() for vm in payload.verification_methods]
        if payload.verification_methods is not None
        else None
    )
    svc_specs = (
        [s.dict() for s in payload.service_endpoints]
        if payload.service_endpoints is not None
        else None
    )

    doc = doc_services.update_draft(
        document=doc,
        updated_by=request.auth,
        verification_methods=vm_specs,
        service_endpoints=svc_specs,
    )

    doc = doc_selectors.get_document_by_id(doc_id=doc.id)
    return _doc_detail(doc)

@router.post(
    f"{_P}/{{doc_id}}/verification-methods",
    response={
        201: VerificationMethodResponse,
        400: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=JWTAuth(),
    summary="Ajouter une méthode de vérification à un document",
)
def add_verification_method(
    request: HttpRequest,
    org_id: UUID,
    doc_id: UUID,
    payload: AddVerificationMethodSchema,
):
    require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)
    require_document_owner(request.auth, doc)

    vm = doc_services.add_verification_method(
        document=doc,
        certificate_id=payload.certificate_id,
        method_id_fragment=payload.method_id_fragment,
        relationships=payload.relationships,
        method_type=payload.method_type,
        added_by=request.auth,
    )

    vm = cert_selectors.get_verification_method_with_cert(vm_id=vm.id)
    return 201, _vm_response(vm)


@router.delete(
    f"{_P}/{{doc_id}}/verification-methods/{{vm_id}}",
    response={200: MessageSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Supprimer une méthode de vérification d'un document",
)
def remove_verification_method(
    request: HttpRequest,
    org_id: UUID,
    doc_id: UUID,
    vm_id: UUID,
):
    require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)
    require_document_owner(request.auth, doc)

    doc_services.remove_verification_method(
        document=doc,
        vm_id=vm_id,
        removed_by=request.auth,
    )
    return {"message": "Verification method removed."}


@router.post(
    f"{_P}/{{doc_id}}/submit",
    response={200: DocDetailSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Soumettre le document pour examen (DRAFT → PENDING_REVIEW)",
)
def submit_for_review(request: HttpRequest, org_id: UUID, doc_id: UUID):
    require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)
    require_document_owner(request.auth, doc)

    doc = doc_services.submit_for_review(document=doc, submitted_by=request.auth)

    doc = doc_selectors.get_document_by_id(doc_id=doc.id)
    return _doc_detail(doc)


@router.post(
    f"{_P}/{{doc_id}}/unsubmit",
    response={200: DocDetailSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Annuler la soumission d'un document (PENDING_REVIEW → DRAFT)",
)
def unsubmit_document(request: HttpRequest, org_id: UUID, doc_id: UUID):
    require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)

    # We use require_document_owner_or_admin so that the owner OR an org admin can unsubmit it
    require_document_owner_or_admin(request.auth, org_id, doc, action="unsubmit")

    doc = doc_services.unsubmit_document(document=doc, unsubmitted_by=request.auth)

    doc = doc_selectors.get_document_by_id(doc_id=doc.id)
    return _doc_detail(doc)


@router.post(
    f"{_P}/{{doc_id}}/approve",
    response={200: DocDetailSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Approuver le document (PENDING_REVIEW → APPROVED)",
)
def approve_document(
    request: HttpRequest,
    org_id: UUID,
    doc_id: UUID,
    payload: ReviewSchema,
):
    require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)
    doc = _get_doc_or_404(doc_id, org_id)
    require_document_reviewer(request.auth, org_id, doc)

    doc = doc_services.approve_document(
        document=doc,
        approved_by=request.auth,
        comment=payload.comment,
    )

    doc = doc_selectors.get_document_by_id(doc_id=doc.id)
    return _doc_detail(doc)


@router.post(
    f"{_P}/{{doc_id}}/reject",
    response={200: DocDetailSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Rejeter le document (PENDING_REVIEW → REJECTED)",
)
def reject_document(
    request: HttpRequest,
    org_id: UUID,
    doc_id: UUID,
    payload: ReviewSchema,
):
    require_permission(request.auth, org_id, Permission.MANAGE_MEMBERS)
    doc = _get_doc_or_404(doc_id, org_id)
    require_document_reviewer(request.auth, org_id, doc)

    doc = doc_services.reject_document(
        document=doc,
        rejected_by=request.auth,
        reason=payload.comment,
    )

    doc = doc_selectors.get_document_by_id(doc_id=doc.id)
    return _doc_detail(doc)


@router.post(
    f"{_P}/{{doc_id}}/publish",
    response={200: DocDetailSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Signer et publier le document (ou re-publier avec nouvelle version)",
)
def publish_document(request: HttpRequest, org_id: UUID, doc_id: UUID):
    """
    Signer et publier un document DID.

    Flux autorisés :
      - ORG_ADMIN sur DRAFT : publication directe (ignore l'examen)
      - Tout rôle sur APPROVED : publication après examen
      - Propriétaire ou ORG_ADMIN sur PUBLISHED : re-publier (nouvelle version du draft_content)
    """
    membership = require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)
    require_document_owner_or_admin(request.auth, org_id, doc, action="publish")

    skip_review = _is_admin(membership)

    doc = doc_services.sign_and_publish(
        document=doc,
        published_by=request.auth,
        skip_review=skip_review,
    )

    doc = doc_selectors.get_document_by_id(doc_id=doc.id)
    return _doc_detail(doc)


@router.post(
    f"{_P}/{{doc_id}}/deactivate",
    response={200: MessageSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Désactiver un document publié",
)
def deactivate_document(
    request: HttpRequest,
    org_id: UUID,
    doc_id: UUID,
    payload: DeactivateSchema,
):
    require_permission(request.auth, org_id, Permission.MUTATE_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)
    require_document_owner_or_admin(request.auth, org_id, doc, action="deactivate")

    doc_services.deactivate_document(
        document=doc,
        deactivated_by=request.auth,
        reason=payload.reason,
    )
    return {"message": f"Document '{doc.label}' has been deactivated."}



@router.get(
    f"{_P}/{{doc_id}}/versions",
    response=PaginatedResponse,
    auth=JWTAuth(),
    summary="Liste des versions publiées d'un document",
)
def list_versions(
    request: HttpRequest,
    org_id: UUID,
    doc_id: UUID,
    page: int = 1,
    page_size: int = 25,
):
    membership = require_permission(request.auth, org_id, Permission.VIEW_DOCUMENTS)
    doc = _get_doc_or_404(doc_id, org_id)

    if not _can_view_all(membership) and doc.owner_id != request.auth.id:
        raise NotFoundError("Document not found.")

    qs = doc_selectors.get_document_versions(document_id=doc_id)
    sliced_qs, total = paginate_queryset(
        queryset=qs,
        page=page,
        page_size=page_size,
        max_page_size=100,
    )
    return {
        "count": total,
        "results": [_version_response(v) for v in sliced_qs],
    }


# Try

@router.get(
    f"{_P}/{{doc_id}}/vc.json",
    response={200: dict, 404: ErrorSchema},
    summary="Obtenir un Identifiant Vérifiable pour un document publié",
)
def get_verifiable_credential(request: HttpRequest, org_id: UUID, doc_id: UUID):
    doc = doc_selectors.get_document_by_id(doc_id=doc_id)
    if doc is None or str(doc.organization_id) != str(org_id):
        raise NotFoundError("Document not found.")

    vc = doc_selectors.get_verifiable_credential(doc)
    if vc is None:
        raise NotFoundError(
            "Verifiable Credential not available. Document must be published."
        )
    return vc
