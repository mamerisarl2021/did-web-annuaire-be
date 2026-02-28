"""
Certificate services (write operations).

Upload flow:
  1. Save PEM via files app (upload_certificate_file)
  2. Call JAR --metadata to extract JWK + cert metadata
  3. Create Certificate + CertificateVersion
  4. Log audit entry

Rotation flow:
  1. Save new PEM
  2. Extract metadata
  3. Create new CertificateVersion (mark as current)
  4. Archive old version (is_current=False)
  5. Update Certificate.current_version

Revocation flow:
  1. Set Certificate.status = REVOKED
  2. Cascade: set is_active=False on all linked DocumentVerificationMethods
  3. Log audit entry
"""

from datetime import datetime
from uuid import UUID

import structlog
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from src.apps.certificates.models import Certificate, CertificateStatus, CertificateVersion
from src.apps.files.services import upload_certificate_file
from src.apps.users.models import User
from src.common.exceptions import ConflictError, NotFoundError, ValidationError
from src.integrations.cert_service import extract_metadata

logger = structlog.get_logger(__name__)


@transaction.atomic
def upload_certificate(
    *,
    organization,
    label: str,
    file: UploadedFile,
    uploaded_by: User,
    p12_password: str | None = None,
) -> Certificate:
    """
    Upload a new certificate.

    1. Saves the file via the files app
    2. Calls the JAR to extract JWK + metadata
    3. Creates Certificate + first CertificateVersion

    Returns the Certificate instance.
    """
    from src.apps.certificates.selectors import certificate_label_exists

    # Validate label uniqueness
    label = label.strip()
    if not label:
        raise ValidationError("Certificate label is required.")

    if certificate_label_exists(organization_id=organization.id, label=label):
        raise ConflictError(f"Certificate label '{label}' already exists in this organization.")

    # 1. Save file
    file_instance = upload_certificate_file(file=file, uploaded_by=uploaded_by)

    # 2. Extract metadata via JAR
    file_instance.file.seek(0)
    cert_bytes = file_instance.file.read()
    metadata = extract_metadata(cert_pem_bytes=cert_bytes, p12_password=p12_password)

    # 3. Create Certificate
    cert = Certificate.objects.create(
        organization=organization,
        label=label,
        status=CertificateStatus.ACTIVE,
        created_by=uploaded_by,
    )

    # 4. Create first version
    version = _create_version(
        certificate=cert,
        version_number=1,
        file_instance=file_instance,
        metadata=metadata,
        uploaded_by=uploaded_by,
        is_current=True,
    )

    cert.current_version = version
    cert.save(update_fields=["current_version", "updated_at"])

    # 5. Audit
    _log_cert_audit(
        actor=uploaded_by,
        action="CERT_UPLOADED",
        certificate=cert,
        description=f"Certificate '{label}' uploaded ({metadata.get('key_type', '?')} "
                    f"{metadata.get('key_curve', metadata.get('key_size', ''))})",
        metadata={
            "key_type": metadata.get("key_type"),
            "key_curve": metadata.get("key_curve", ""),
            "fingerprint": metadata.get("fingerprint_sha256"),
        },
    )

    logger.info(
        "certificate_uploaded",
        cert_id=str(cert.id),
        label=label,
        key_type=metadata.get("key_type"),
    )
    return cert


@transaction.atomic
def rotate_certificate(
    *,
    certificate: Certificate,
    file: UploadedFile,
    uploaded_by: User,
    p12_password: str | None = None,
) -> CertificateVersion:
    """
    Rotate a certificate — upload a new version.

    - Certificate must be ACTIVE.
    - Old version is archived (is_current=False).
    - New version becomes current.
    """
    if certificate.status != CertificateStatus.ACTIVE:
        raise ValidationError(
            f"Cannot rotate a {certificate.status} certificate. Only ACTIVE certificates can be rotated."
        )

    # Save file + extract
    file_instance = upload_certificate_file(file=file, uploaded_by=uploaded_by)
    file_instance.file.seek(0)
    cert_bytes = file_instance.file.read()
    metadata = extract_metadata(cert_pem_bytes=cert_bytes, p12_password=p12_password)

    # Archive current version
    current_version_number = 0
    if certificate.current_version:
        certificate.current_version.is_current = False
        certificate.current_version.save(update_fields=["is_current", "updated_at"])
        current_version_number = certificate.current_version.version_number

    # Create new version
    new_version = _create_version(
        certificate=certificate,
        version_number=current_version_number + 1,
        file_instance=file_instance,
        metadata=metadata,
        uploaded_by=uploaded_by,
        is_current=True,
    )

    certificate.current_version = new_version
    certificate.save(update_fields=["current_version", "updated_at"])

    # Audit
    _log_cert_audit(
        actor=uploaded_by,
        action="CERT_ROTATED",
        certificate=certificate,
        description=f"Certificate '{certificate.label}' rotated to v{new_version.version_number}",
        metadata={
            "old_version": current_version_number,
            "new_version": new_version.version_number,
            "fingerprint": metadata.get("fingerprint_sha256"),
        },
    )

    logger.info(
        "certificate_rotated",
        cert_id=str(certificate.id),
        new_version=new_version.version_number,
    )
    return new_version


@transaction.atomic
def revoke_certificate(
    *,
    certificate: Certificate,
    revoked_by: User,
    reason: str = "",
) -> Certificate:
    """
    Revoke a certificate.

    - Sets status to REVOKED.
    - Cascades: deactivates all linked verification methods in DID documents.
    """
    if certificate.status == CertificateStatus.REVOKED:
        raise ValidationError("Certificate is already revoked.")

    old_status = certificate.status
    certificate.status = CertificateStatus.REVOKED
    certificate.save(update_fields=["status", "updated_at"])

    # Cascade to verification methods
    from src.apps.documents.models import DocumentVerificationMethod
    affected = DocumentVerificationMethod.objects.filter(
        certificate=certificate,
        is_active=True,
    ).update(is_active=False)

    # Audit
    _log_cert_audit(
        actor=revoked_by,
        action="CERT_REVOKED",
        certificate=certificate,
        description=f"Certificate '{certificate.label}' revoked. "
                    f"{affected} verification method(s) deactivated."
                    f"{f' Reason: {reason}' if reason else ''}",
        metadata={
            "old_status": old_status,
            "reason": reason,
            "affected_verification_methods": affected,
        },
    )

    logger.info(
        "certificate_revoked",
        cert_id=str(certificate.id),
        affected_methods=affected,
    )
    return certificate


# ── Internal helpers ─────────────────────────────────────────────────────

def _create_version(
    *,
    certificate: Certificate,
    version_number: int,
    file_instance,
    metadata: dict,
    uploaded_by: User,
    is_current: bool,
) -> CertificateVersion:
    """Create a CertificateVersion from extracted metadata."""
    not_valid_before = _parse_iso_datetime(metadata.get("not_valid_before"))
    not_valid_after = _parse_iso_datetime(metadata.get("not_valid_after"))

    return CertificateVersion.objects.create(
        certificate=certificate,
        version_number=version_number,
        certificate_file=file_instance,
        public_key_jwk=metadata.get("public_key_jwk", {}),
        subject_dn=metadata.get("subject_dn", ""),
        issuer_dn=metadata.get("issuer_dn", ""),
        serial_number=metadata.get("serial_number", ""),
        not_valid_before=not_valid_before,
        not_valid_after=not_valid_after,
        key_type=metadata.get("key_type", ""),
        key_curve=metadata.get("key_curve", ""),
        key_size=metadata.get("key_size"),
        fingerprint_sha256=metadata.get("fingerprint_sha256", ""),
        is_current=is_current,
        uploaded_by=uploaded_by,
    )


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    # The JAR outputs ISO 8601 e.g. "2025-12-25T14:32:06Z"
    dt = parse_datetime(value)
    if dt and timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def _log_cert_audit(*, actor, action, certificate, description, metadata):
    """Log audit entry for certificate operations."""
    try:
        from src.apps.audits.services import log_action
        log_action(
            actor=actor,
            action=action,
            resource_type="CERTIFICATE",
            resource_id=certificate.id,
            organization=certificate.organization,
            description=description,
            metadata=metadata,
        )
    except Exception as e:
        # Audit logging should never break the main operation
        logger.warning("audit_log_failed", error=str(e))
