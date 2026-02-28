"""
Certificate selectors (read operations).
"""

from uuid import UUID

from django.db.models import QuerySet

from src.apps.certificates.models import Certificate, CertificateVersion, CertificateStatus


def get_certificate_by_id(*, cert_id: UUID) -> Certificate | None:
    try:
        return (
            Certificate.objects
            .select_related("organization", "current_version", "created_by")
            .get(id=cert_id)
        )
    except Certificate.DoesNotExist:
        return None


def get_org_certificates(*, organization_id: UUID) -> QuerySet[Certificate]:
    """All certificates for an organization, ordered by most recent."""
    return (
        Certificate.objects
        .filter(organization_id=organization_id)
        .select_related("current_version", "created_by")
        .order_by("-created_at")
    )


def get_certificate_versions(*, certificate_id: UUID) -> QuerySet[CertificateVersion]:
    """All versions of a certificate, newest first."""
    return (
        CertificateVersion.objects
        .filter(certificate_id=certificate_id)
        .select_related("uploaded_by", "certificate_file")
        .order_by("-version_number")
    )


def get_active_org_certificates(*, organization_id: UUID) -> QuerySet[Certificate]:
    """Only ACTIVE certificates for an organization."""
    return (
        Certificate.objects
        .filter(
            organization_id=organization_id,
            status=CertificateStatus.ACTIVE,
        )
        .select_related("current_version")
        .order_by("-created_at")
    )


def certificate_label_exists(*, organization_id: UUID, label: str, exclude_id: UUID | None = None) -> bool:
    qs = Certificate.objects.filter(organization_id=organization_id, label=label)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return qs.exists()
