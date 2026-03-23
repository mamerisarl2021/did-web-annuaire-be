"""
Endpoints de l'API Certificat.

Monté sur : /api/v2/org/organizations/{org_id}/certificates/

Portée :
  - ORG_ADMIN :  voit TOUS les certifs. de l'org, peut faire tourner/révoquer n'importe lequel
  - ORG_MEMBER : voit UNIQUEMENT ses propres certifs (created_by = self), peut faire tourner les siens
  - AUDITOR :    voit TOUT (lecture seule)

Tous les endpoints nécessitent une authentification JWT et l'appartenance à l'org cible.
Upload et rotate utilisent des données multipart form (fichier + métadonnées).
"""

from uuid import UUID

from django.http import HttpRequest
from ninja import File, Form, Router, UploadedFile as NinjaFile
from ninja_jwt.authentication import JWTAuth

from src.apps.certificates import selectors as cert_selectors
from src.apps.certificates import services as cert_services
from src.apps.certificates.models import CertificateVersion
from src.apps.certificates.schemas import (
    CertDetailSchema,
    CertListItemSchema,
    CertRevokeSchema,
    CertVersionDetailSchema,
    CertVersionSummarySchema,
    ErrorSchema,
    MessageSchema,
)
from src.common.exceptions import NotFoundError, PermissionDeniedError
from src.common.permissions import Permission, require_permission
from src.common.types import Role

router = Router(tags=["Certificates"])

_P = "/organizations/{org_id}/certificates"


# ── Aides à la portée ───────────────────────────────────────────────────


def _can_view_all(membership) -> bool:
    """ORG_ADMIN et AUDITOR voient tous les certificats de l'org."""
    return membership.role in (Role.ORG_ADMIN, Role.AUDITOR)


def _require_cert_access(cert, user, membership, action="access"):
    """
    Appliquer la portée de propriété : ORG_MEMBER ne peut accéder qu'à ses propres certifs.
    ORG_ADMIN et AUDITOR peuvent accéder à n'importe quel certif. dans l'org.
    """
    if _can_view_all(membership):
        return
    if cert.created_by_id == user.id:
        return
    raise PermissionDeniedError(f"You can only {action} certificates you uploaded.")


def _require_cert_mutate(cert, user, membership, action="modify"):
    """
    Appliquer la prot. pr les mutations : ORG_MEMBER ne pet modif que ses propres certifs.
    ORG_ADMIN peut modifier n'importe quel certificat dans l'organisation.
    """
    if membership.role == Role.ORG_ADMIN:
        return
    if cert.created_by_id == user.id:
        return
    raise PermissionDeniedError(f"You can only {action} certificates you uploaded.")


# ── Aides à la sérialisation ────────────────────────────────────────────


def _cert_list_item(cert) -> dict:
    cv = cert.current_version
    return {
        "id": cert.id,
        "label": cert.label,
        "status": cert.status,
        "key_type": cv.key_type if cv else "",
        "key_curve": cv.key_curve if cv else "",
        "subject_dn": cv.subject_dn if cv else "",
        "fingerprint_sha256": cv.fingerprint_sha256 if cv else "",
        "not_valid_after": cv.not_valid_after.isoformat()
        if cv and cv.not_valid_after
        else None,
        "created_by_email": cert.created_by.email if cert.created_by else "",
        "created_at": cert.created_at.isoformat(),
        "version_count": cert.versions.count(),
    }


def _version_summary(v: CertificateVersion) -> dict:
    return {
        "id": v.id,
        "version_number": v.version_number,
        "key_type": v.key_type,
        "key_curve": v.key_curve,
        "subject_dn": v.subject_dn,
        "issuer_dn": v.issuer_dn,
        "serial_number": v.serial_number,
        "not_valid_before": v.not_valid_before.isoformat()
        if v.not_valid_before
        else None,
        "not_valid_after": v.not_valid_after.isoformat() if v.not_valid_after else None,
        "fingerprint_sha256": v.fingerprint_sha256,
        "is_current": v.is_current,
        "created_at": v.created_at.isoformat(),
    }


def _version_detail(v: CertificateVersion) -> dict:
    d = _version_summary(v)
    d.update(
        {
            "public_key_jwk": v.public_key_jwk,
            "key_size": v.key_size,
            "uploaded_by_email": v.uploaded_by.email if v.uploaded_by else "",
            "file_name": v.certificate_file.original_file_name
            if v.certificate_file
            else "",
        }
    )
    return d


def _cert_detail(cert) -> dict:
    linked = cert_selectors.count_linked_documents_for_cert(cert_id=cert.id)

    return {
        "id": cert.id,
        "label": cert.label,
        "status": cert.status,
        "created_by_email": cert.created_by.email if cert.created_by else "",
        "created_by_id": cert.created_by_id,
        "created_at": cert.created_at.isoformat(),
        "current_version": _version_detail(cert.current_version)
        if cert.current_version
        else None,
        "version_count": cert.versions.count(),
        "linked_documents": linked,
    }


# ── Liste des certificats ───────────────────────────────────────────────


@router.get(
    f"{_P}",
    response=list[CertListItemSchema],
    auth=JWTAuth(),
    summary="Lister les certificats (portée par rôle)",
)
def list_certificates(request: HttpRequest, org_id: UUID):
    """
    ORG_ADMIN / AUDITOR : tous les certificats de l'organisation.
    ORG_MEMBER : uniquement les certificats téléchargés par l'ut. demandeur.
    """
    membership = require_permission(request.auth, org_id, Permission.VIEW_CERTIFICATES)

    if _can_view_all(membership):
        certs = cert_selectors.get_org_certificates(organization_id=org_id)
    else:
        certs = cert_selectors.get_user_certificates(
            organization_id=org_id,
            user_id=request.auth.id,
        )

    return [_cert_list_item(c) for c in certs]


# ── Télécharger un certificat ───────────────────────────────────────────


@router.post(
    f"{_P}/upload",
    response={201: CertDetailSchema, 400: ErrorSchema, 409: ErrorSchema},
    auth=JWTAuth(),
    summary="Télécharger un nouveau certificat",
)
def upload_certificate(
    request: HttpRequest,
    org_id: UUID,
    label: str = Form(...),
    file: NinjaFile = File(...),
    p12_password: str = Form(None),
):
    membership = require_permission(
        request.auth, org_id, Permission.MUTATE_CERTIFICATES
    )

    cert = cert_services.upload_certificate(
        organization=membership.organization,
        label=label,
        file=file,
        uploaded_by=request.auth,
        p12_password=p12_password if p12_password else None,
    )

    cert = cert_selectors.get_certificate_by_id(cert_id=cert.id)
    return 201, _cert_detail(cert)


# ── Détails du certificat ───────────────────────────────────────────────


@router.get(
    f"{_P}/{{cert_id}}",
    response={200: CertDetailSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Obtenir les détails du certificat",
)
def get_certificate(request: HttpRequest, org_id: UUID, cert_id: UUID):
    membership = require_permission(request.auth, org_id, Permission.VIEW_CERTIFICATES)

    cert = cert_selectors.get_certificate_by_id(cert_id=cert_id)
    if cert is None or str(cert.organization_id) != str(org_id):
        raise NotFoundError("Certificate not found.")

    _require_cert_access(cert, request.auth, membership, action="view")

    return _cert_detail(cert)


# ── Faire tourner le certificat ─────────────────────────────────────────


@router.post(
    f"{_P}/{{cert_id}}/rotate",
    response={200: CertDetailSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Faire tourner un certificat (télécharger no. version)",
)
def rotate_certificate(
    request: HttpRequest,
    org_id: UUID,
    cert_id: UUID,
    file: NinjaFile = File(...),
    p12_password: str = Form(None),
):
    membership = require_permission(
        request.auth, org_id, Permission.MUTATE_CERTIFICATES
    )

    cert = cert_selectors.get_certificate_by_id(cert_id=cert_id)
    if cert is None or str(cert.organization_id) != str(org_id):
        raise NotFoundError("Certificate not found.")

    _require_cert_mutate(cert, request.auth, membership, action="rotate")

    cert_services.rotate_certificate(
        certificate=cert,
        file=file,
        uploaded_by=request.auth,
        p12_password=p12_password if p12_password else None,
    )

    cert = cert_selectors.get_certificate_by_id(cert_id=cert.id)
    return _cert_detail(cert)


# ── Révoquer le certificat ──────────────────────────────────────────────


@router.post(
    f"{_P}/{{cert_id}}/revoke",
    response={200: MessageSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Révoquer un certificat",
)
def revoke_certificate(
    request: HttpRequest,
    org_id: UUID,
    cert_id: UUID,
    payload: CertRevokeSchema,
):
    membership = require_permission(
        request.auth, org_id, Permission.REVOKE_CERTIFICATES
    )

    cert = cert_selectors.get_certificate_by_id(cert_id=cert_id)
    if cert is None or str(cert.organization_id) != str(org_id):
        raise NotFoundError("Certificate not found.")

    # ORG_ADMIN peut révoquer n'im. lequel ; ORG_MEMBER uniq. le sien
    _require_cert_mutate(cert, request.auth, membership, action="revoke")

    cert_services.revoke_certificate(
        certificate=cert,
        revoked_by=request.auth,
        reason=payload.reason,
    )

    return {"message": f"Certificate '{cert.label}' has been revoked."}


# ── Historique des versions ─────────────────────────────────────────────


@router.get(
    f"{_P}/{{cert_id}}/versions",
    response=list[CertVersionSummarySchema],
    auth=JWTAuth(),
    summary="Lister les versions de certificats",
)
def list_versions(request: HttpRequest, org_id: UUID, cert_id: UUID):
    membership = require_permission(request.auth, org_id, Permission.VIEW_CERTIFICATES)

    cert = cert_selectors.get_certificate_by_id(cert_id=cert_id)
    if cert is None or str(cert.organization_id) != str(org_id):
        raise NotFoundError("Certificate not found.")

    _require_cert_access(cert, request.auth, membership, action="view versions of")

    versions = cert_selectors.get_certificate_versions(certificate_id=cert_id)
    return [_version_summary(v) for v in versions]


# ── Détails de la version ───────────────────────────────────────────────


@router.get(
    f"{_P}/{{cert_id}}/versions/{{version_id}}",
    response={200: CertVersionDetailSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Détails de v. du certif (inclut JWK)",
)
def get_version(request: HttpRequest, org_id: UUID, cert_id: UUID, version_id: UUID):
    membership = require_permission(request.auth, org_id, Permission.VIEW_CERTIFICATES)

    cert = cert_selectors.get_certificate_by_id(cert_id=cert_id)
    if cert is None or str(cert.organization_id) != str(org_id):
        raise NotFoundError("Certificate not found.")

    _require_cert_access(cert, request.auth, membership, action="view")

    try:
        version = CertificateVersion.objects.select_related(
            "certificate__organization", "uploaded_by", "certificate_file"
        ).get(id=version_id, certificate_id=cert_id)
    except CertificateVersion.DoesNotExist:
        raise NotFoundError("Version not found.")

    return _version_detail(version)
