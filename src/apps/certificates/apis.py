"""
Certificate API endpoints.

Mounted at: /api/v2/org/   (alongside orgadmin router)
Full paths:  /api/v2/org/organizations/{org_id}/certificates/...

All endpoints require JWT auth and membership in the target org.
Upload and rotate use multipart form data (file + metadata).
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
from src.common.exceptions import NotFoundError
from src.common.permissions import Permission, require_permission

router = Router(tags=["Certificates"])

# ── Path prefix (avoids putting {org_id} in add_router prefix) ──────────

_P = "/organizations/{org_id}/certificates"


# ── Helpers ──────────────────────────────────────────────────────────────


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
        "not_valid_after": cv.not_valid_after.isoformat() if cv and cv.not_valid_after else None,
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
        "not_valid_before": v.not_valid_before.isoformat() if v.not_valid_before else None,
        "not_valid_after": v.not_valid_after.isoformat() if v.not_valid_after else None,
        "fingerprint_sha256": v.fingerprint_sha256,
        "is_current": v.is_current,
        "created_at": v.created_at.isoformat(),
    }


def _version_detail(v: CertificateVersion) -> dict:
    d = _version_summary(v)
    d.update({
        "public_key_jwk": v.public_key_jwk,
        "key_size": v.key_size,
        "uploaded_by_email": v.uploaded_by.email if v.uploaded_by else "",
        "file_name": v.certificate_file.original_file_name if v.certificate_file else "",
    })
    return d


def _cert_detail(cert) -> dict:
    from src.apps.documents.models import DocumentVerificationMethod

    linked = DocumentVerificationMethod.objects.filter(
        certificate=cert
    ).values("document_id").distinct().count()

    return {
        "id": cert.id,
        "label": cert.label,
        "status": cert.status,
        "created_by_email": cert.created_by.email if cert.created_by else "",
        "created_at": cert.created_at.isoformat(),
        "current_version": _version_detail(cert.current_version) if cert.current_version else None,
        "version_count": cert.versions.count(),
        "linked_documents": linked,
    }


# ── List certificates ────────────────────────────────────────────────────


@router.get(
    f"{_P}",
    response=list[CertListItemSchema],
    auth=JWTAuth(),
    summary="List organization certificates",
)
def list_certificates(request: HttpRequest, org_id: UUID):
    require_permission(request.auth, org_id, Permission.VIEW_CERTIFICATES)
    certs = cert_selectors.get_org_certificates(organization_id=org_id)
    return [_cert_list_item(c) for c in certs]

# ── Upload certificate ───────────────────────────────────────────────────


@router.post(
    f"{_P}/upload",
    response={201: CertDetailSchema, 400: ErrorSchema, 409: ErrorSchema},
    auth=JWTAuth(),
    summary="Upload a new certificate",
)
def upload_certificate(
    request: HttpRequest,
    org_id: UUID,
    label: str = Form(...),
    file: NinjaFile = File(...),
    p12_password: str = Form(None),
):
    membership = require_permission(request.auth, org_id, Permission.MUTATE_CERTIFICATES)

    cert = cert_services.upload_certificate(
        organization=membership.organization,
        label=label,
        file=file,
        uploaded_by=request.auth,
        p12_password=p12_password if p12_password else None,
    )

    # Reload with relations
    cert = cert_selectors.get_certificate_by_id(cert_id=cert.id)
    return 201, _cert_detail(cert)


# ── Certificate detail ───────────────────────────────────────────────────


@router.get(
    f"{_P}/{{cert_id}}",
    response={200: CertDetailSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Get certificate detail",
)
def get_certificate(request: HttpRequest, org_id: UUID, cert_id: UUID):
    require_permission(request.auth, org_id, Permission.VIEW_CERTIFICATES)

    cert = cert_selectors.get_certificate_by_id(cert_id=cert_id)
    if cert is None or str(cert.organization_id) != str(org_id):
        raise NotFoundError("Certificate not found.")

    return _cert_detail(cert)


# ── Rotate certificate ──────────────────────────────────────────────────


@router.post(
    f"{_P}/{{cert_id}}/rotate",
    response={200: CertDetailSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Rotate a certificate (upload new version)",
)
def rotate_certificate(
    request: HttpRequest,
    org_id: UUID,
    cert_id: UUID,
    file: NinjaFile = File(...),
    p12_password: str = Form(None),
):
    require_permission(request.auth, org_id, Permission.MUTATE_CERTIFICATES)

    cert = cert_selectors.get_certificate_by_id(cert_id=cert_id)
    if cert is None or str(cert.organization_id) != str(org_id):
        raise NotFoundError("Certificate not found.")

    cert_services.rotate_certificate(
        certificate=cert,
        file=file,
        uploaded_by=request.auth,
        p12_password=p12_password if p12_password else None,
    )

    cert = cert_selectors.get_certificate_by_id(cert_id=cert.id)
    return _cert_detail(cert)


# ── Revoke certificate ──────────────────────────────────────────────────


@router.post(
    f"{_P}/{{cert_id}}/revoke",
    response={200: MessageSchema, 400: ErrorSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Revoke a certificate",
)
def revoke_certificate(
    request: HttpRequest,
    org_id: UUID,
    cert_id: UUID,
    payload: CertRevokeSchema,
):
    require_permission(request.auth, org_id, Permission.REVOKE_CERTIFICATES)

    cert = cert_selectors.get_certificate_by_id(cert_id=cert_id)
    if cert is None or str(cert.organization_id) != str(org_id):
        raise NotFoundError("Certificate not found.")

    cert_services.revoke_certificate(
        certificate=cert,
        revoked_by=request.auth,
        reason=payload.reason,
    )

    return {"message": f"Certificate '{cert.label}' has been revoked."}


# ── Version history ──────────────────────────────────────────────────────


@router.get(
    f"{_P}/{{cert_id}}/versions",
    response=list[CertVersionSummarySchema],
    auth=JWTAuth(),
    summary="List certificate versions",
)
def list_versions(request: HttpRequest, org_id: UUID, cert_id: UUID):
    require_permission(request.auth, org_id, Permission.VIEW_CERTIFICATES)

    cert = cert_selectors.get_certificate_by_id(cert_id=cert_id)
    if cert is None or str(cert.organization_id) != str(org_id):
        raise NotFoundError("Certificate not found.")

    versions = cert_selectors.get_certificate_versions(certificate_id=cert_id)
    return [_version_summary(v) for v in versions]


# ── Version detail ───────────────────────────────────────────────────────


@router.get(
    f"{_P}/{{cert_id}}/versions/{{version_id}}",
    response={200: CertVersionDetailSchema, 404: ErrorSchema},
    auth=JWTAuth(),
    summary="Get certificate version detail (includes JWK)",
)
def get_version(request: HttpRequest, org_id: UUID, cert_id: UUID, version_id: UUID):
    require_permission(request.auth, org_id, Permission.VIEW_CERTIFICATES)

    try:
        version = (
            CertificateVersion.objects
            .select_related("certificate__organization", "uploaded_by", "certificate_file")
            .get(id=version_id, certificate_id=cert_id)
        )
    except CertificateVersion.DoesNotExist:
        raise NotFoundError("Version not found.")

    if str(version.certificate.organization_id) != str(org_id):
        raise NotFoundError("Version not found.")

    return _version_detail(version)