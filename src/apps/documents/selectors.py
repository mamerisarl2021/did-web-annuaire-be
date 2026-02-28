"""
DID Document selectors (read operations).

Scoping rules:
  - All org members can VIEW all documents in the organization.
  - Filtering by owner is available for "my documents" views.
  - AUDITOR sees all documents (read-only).
"""

from uuid import UUID

from django.db.models import QuerySet

from src.apps.documents.models import (
    DIDDocument,
    DIDDocumentVersion,
    DocumentStatus,
    DocumentVerificationMethod,
)


# ── Single document lookups ──────────────────────────────────────────────


def get_document_by_id(*, doc_id: UUID) -> DIDDocument | None:
    try:
        return (
            DIDDocument.objects
            .select_related("organization", "owner", "current_version",
                            "submitted_by", "reviewed_by", "created_by")
            .get(id=doc_id)
        )
    except DIDDocument.DoesNotExist:
        return None


# ── List queries ─────────────────────────────────────────────────────────


def get_org_documents(*, organization_id: UUID) -> QuerySet[DIDDocument]:
    """All documents in an organization, newest first."""
    return (
        DIDDocument.objects
        .filter(organization_id=organization_id)
        .select_related("owner", "current_version")
        .order_by("-created_at")
    )


def get_user_documents(*, organization_id: UUID, user_id: UUID) -> QuerySet[DIDDocument]:
    """Documents owned by a specific user in an organization."""
    return (
        DIDDocument.objects
        .filter(organization_id=organization_id, owner_id=user_id)
        .select_related("owner", "current_version")
        .order_by("-created_at")
    )


def get_documents_pending_review(*, organization_id: UUID) -> QuerySet[DIDDocument]:
    """Documents awaiting ORG_ADMIN review."""
    return (
        DIDDocument.objects
        .filter(
            organization_id=organization_id,
            status=DocumentStatus.PENDING_REVIEW,
        )
        .select_related("owner", "submitted_by")
        .order_by("submitted_at")
    )


def get_documents_by_status(
    *, organization_id: UUID, status: str,
) -> QuerySet[DIDDocument]:
    """Filter documents by status."""
    return (
        DIDDocument.objects
        .filter(organization_id=organization_id, status=status)
        .select_related("owner", "current_version")
        .order_by("-created_at")
    )


# ── Verification methods ─────────────────────────────────────────────────


def get_document_verification_methods(
    *, document_id: UUID,
) -> QuerySet[DocumentVerificationMethod]:
    """All verification methods for a document, with certificate data."""
    return (
        DocumentVerificationMethod.objects
        .filter(document_id=document_id)
        .select_related("certificate__current_version", "certificate__created_by")
        .order_by("created_at")
    )


def get_active_verification_methods(
    *, document_id: UUID,
) -> QuerySet[DocumentVerificationMethod]:
    """Only active verification methods (cert not revoked)."""
    return (
        DocumentVerificationMethod.objects
        .filter(document_id=document_id, is_active=True)
        .select_related("certificate__current_version")
        .order_by("created_at")
    )


# ── Version history ──────────────────────────────────────────────────────


def get_document_versions(*, document_id: UUID) -> QuerySet[DIDDocumentVersion]:
    """All versions of a document, newest first."""
    return (
        DIDDocumentVersion.objects
        .filter(document_id=document_id)
        .select_related("published_by")
        .order_by("-version_number")
    )


def get_document_version(
    *, document_id: UUID, version_id: UUID,
) -> DIDDocumentVersion | None:
    try:
        return (
            DIDDocumentVersion.objects
            .select_related("document__organization", "published_by")
            .get(id=version_id, document_id=document_id)
        )
    except DIDDocumentVersion.DoesNotExist:
        return None


# ── Validation helpers ───────────────────────────────────────────────────


def document_label_exists(
    *, organization_id: UUID, owner_id: UUID, label: str,
    exclude_id: UUID | None = None,
) -> bool:
    """Check if a label is already used by this owner in this org."""
    qs = DIDDocument.objects.filter(
        organization_id=organization_id, owner_id=owner_id, label=label,
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return qs.exists()


def count_org_documents(*, organization_id: UUID) -> int:
    return DIDDocument.objects.filter(organization_id=organization_id).count()


def count_user_documents(*, organization_id: UUID, user_id: UUID) -> int:
    return DIDDocument.objects.filter(
        organization_id=organization_id, owner_id=user_id,
    ).count()