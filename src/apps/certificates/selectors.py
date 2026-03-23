"""
Sélecteurs de certificats (opérations de lecture).
"""

from uuid import UUID

from django.db.models import QuerySet

from src.apps.certificates.models import (
    Certificate,
    CertificateStatus,
    CertificateVersion,
)


def get_certificate_by_id(*, cert_id: UUID) -> Certificate | None:
    try:
        return Certificate.objects.select_related(
            "organization", "current_version", "created_by"
        ).get(id=cert_id)
    except Certificate.DoesNotExist:
        return None


def get_org_certificates(*, organization_id: UUID) -> QuerySet[Certificate]:
    """Tous les certificats pour une organisation (pour ORG_ADMIN / AUDITOR)."""
    return (
        Certificate.objects.filter(organization_id=organization_id)
        .select_related("current_version", "created_by")
        .order_by("-created_at")
    )


def get_user_certificates(
    *,
    organization_id: UUID,
    user_id: UUID,
) -> QuerySet[Certificate]:
    """Certifs uploadés par un utilisateur spé. dans une organisation (ORG_MEMBER)."""
    return (
        Certificate.objects.filter(
            organization_id=organization_id, created_by_id=user_id
        )
        .select_related("current_version", "created_by")
        .order_by("-created_at")
    )


def get_certificate_versions(*, certificate_id: UUID) -> QuerySet[CertificateVersion]:
    """Toutes les versions d'un certificat, du plus récent au plus ancien."""
    return (
        CertificateVersion.objects.filter(certificate_id=certificate_id)
        .select_related("uploaded_by", "certificate_file")
        .order_by("-version_number")
    )


def get_active_org_certificates(*, organization_id: UUID) -> QuerySet[Certificate]:
    """Uniquement les certificats ACTIVE pour une organisation."""
    return (
        Certificate.objects.filter(
            organization_id=organization_id,
            status=CertificateStatus.ACTIVE,
        )
        .select_related("current_version")
        .order_by("-created_at")
    )


def get_active_user_certificates(
    *,
    organization_id: UUID,
    user_id: UUID,
) -> QuerySet[Certificate]:
    """Uniquement les certificats ACTIVE uploadés par un utilisateur spécifique."""
    return (
        Certificate.objects.filter(
            organization_id=organization_id,
            created_by_id=user_id,
            status=CertificateStatus.ACTIVE,
        )
        .select_related("current_version")
        .order_by("-created_at")
    )


def certificate_label_exists(
    *,
    organization_id: UUID,
    label: str,
    exclude_id: UUID | None = None,
) -> bool:
    qs = Certificate.objects.filter(organization_id=organization_id, label=label)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return qs.exists()


def count_linked_documents_for_cert(*, cert_id: UUID) -> int:
    """
    Compte le nombre de documents DID distincts qui font réf à un certificat donné
    via au moins une DocumentVerificationMethod.
    """
    from src.apps.documents.models import DocumentVerificationMethod

    return (
        DocumentVerificationMethod.objects.filter(certificate_id=cert_id)
        .values("document_id")
        .distinct()
        .count()
    )


def get_verification_method_with_cert(*, vm_id: UUID):
    """
    Récupère une DocumentVerificationMethod avec son certif. et sa version actuelle
    préchargés via select_related.

    Renvoie None s'il n'est pas trouvé.
    """
    from src.apps.documents.models import DocumentVerificationMethod

    try:
        return DocumentVerificationMethod.objects.select_related(
            "certificate",
            "certificate__current_version",
        ).get(id=vm_id)
    except DocumentVerificationMethod.DoesNotExist:
        return None
