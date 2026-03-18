"""
DID Document selectors (read operations).

Scoping:
  - ORG_ADMIN:  sees all org documents
  - ORG_MEMBER: sees only own documents
  - AUDITOR:    sees all org documents (read-only)
"""

from uuid import UUID

from django.db.models import QuerySet

from src.apps.documents.models import (
    DIDDocument,
    DIDDocumentVersion,
    DocumentStatus,
    DocumentVerificationMethod,
)


# ── Single-object lookups ────────────────────────────────────────────────


def get_document_by_id(*, doc_id: UUID) -> DIDDocument | None:
    try:
        return DIDDocument.objects.select_related(
            "organization",
            "owner",
            "created_by",
            "submitted_by",
            "reviewed_by",
            "current_version",
        ).get(id=doc_id)
    except DIDDocument.DoesNotExist:
        return None


# ── List queries ─────────────────────────────────────────────────────────


def get_org_documents(*, organization_id: UUID, user_id: UUID) -> QuerySet[DIDDocument]:
    """All documents for an organization (for ORG_ADMIN / AUDITOR)."""
    from django.db.models import Q

    return (
        DIDDocument.objects.filter(
            Q(organization_id=organization_id)
            & (Q(submitted_at__isnull=False) | Q(owner_id=user_id))
        )
        .select_related("owner", "created_by", "current_version")
        .order_by("-updated_at")
    )


def get_user_documents(
    *, organization_id: UUID, user_id: UUID
) -> QuerySet[DIDDocument]:
    """Documents owned by a specific user within an organization."""
    return (
        DIDDocument.objects.filter(organization_id=organization_id, owner_id=user_id)
        .select_related("owner", "created_by", "current_version")
        .order_by("-updated_at")
    )


def get_pending_review_documents(*, organization_id: UUID) -> QuerySet[DIDDocument]:
    """Documents awaiting review (for ORG_ADMIN dashboard)."""
    return (
        DIDDocument.objects.filter(
            organization_id=organization_id,
            status=DocumentStatus.PENDING_REVIEW,
        )
        .select_related("owner", "created_by", "submitted_by")
        .order_by("submitted_at")
    )


# ── Verification methods ────────────────────────────────────────────────


def get_document_verification_methods(
    *, document_id: UUID
) -> QuerySet[DocumentVerificationMethod]:
    return (
        DocumentVerificationMethod.objects.filter(document_id=document_id)
        .select_related(
            "certificate",
            "certificate__current_version",
            "certificate__created_by",
        )
        .order_by("created_at")
    )


def get_active_verification_methods(
    *, document_id: UUID
) -> QuerySet[DocumentVerificationMethod]:
    return get_document_verification_methods(document_id=document_id).filter(
        is_active=True
    )


# ── Versions ─────────────────────────────────────────────────────────────


def get_document_versions(*, document_id: UUID) -> QuerySet[DIDDocumentVersion]:
    return (
        DIDDocumentVersion.objects.filter(document_id=document_id)
        .select_related("published_by")
        .order_by("-version_number")
    )


# ── Validation helpers ───────────────────────────────────────────────────


def document_label_exists(
    *,
    organization_id: UUID,
    owner_id: UUID,
    label: str,
    exclude_id: UUID | None = None,
) -> bool:
    """Check if a label already exists for this owner in this org."""
    qs = DIDDocument.objects.filter(
        organization_id=organization_id,
        owner_id=owner_id,
        label=label,
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return qs.exists()


def get_org_document_counts(*, organization_id: UUID) -> dict:
    from django.db.models import Count, Q

    return DIDDocument.objects.filter(organization_id=organization_id).aggregate(
        total=Count("id"),
        drafts=Count("id", filter=Q(status=DocumentStatus.DRAFT)),
        pending=Count("id", filter=Q(status=DocumentStatus.PENDING_REVIEW)),
        published=Count("id", filter=Q(status=DocumentStatus.PUBLISHED)),
        deactivated=Count("id", filter=Q(status=DocumentStatus.DEACTIVATED)),
    )


def get_verifiable_credential(document: DIDDocument) -> dict | None:
    """
    Build a Verifiable Credential for a published DID document.

    Pure read operation — no side effects, no DB writes.
    Moved here from services.py to respect the read/write split.
    Returns None if the document is not yet published.
    """
    from django.utils import timezone

    from src.common.did.assembler import build_did_uri, build_verifiable_credential

    if not document.content or document.status == DocumentStatus.DEACTIVATED:
        return None

    did_uri = build_did_uri(
        org_slug=document.organization.slug,
        owner_identifier=document.owner_identifier,
        label=document.label,
    )

    published_at = ""
    version = 0
    if document.current_version:
        published_at = (
            document.current_version.published_at.isoformat()
            if document.current_version.published_at
            else timezone.now().isoformat()
        )
        version = document.current_version.version_number

    owner_name = ""
    if document.owner:
        owner_name = getattr(document.owner, "full_name", "") or document.owner.email

    return build_verifiable_credential(
        did_uri=did_uri,
        did_document=document.content,
        org_name=document.organization.name,
        owner_name=owner_name,
        label=document.label,
        version=version,
        published_at=published_at,
    )
