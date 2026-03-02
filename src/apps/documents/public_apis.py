"""
Public search API endpoints.

These endpoints are accessible WITHOUT authentication.
They expose only published DID documents and approved organizations.

Rate limiting should be enforced at the nginx level or via Django's
cache-based throttling.

Mounted at: /api/v2/public/search/
"""

import math
from uuid import UUID

from django.db.models import Q
from django.http import HttpRequest
from ninja import Query, Router

from src.apps.documents.models import DIDDocument, DocumentStatus
from src.apps.organizations.models import Organization
from src.common.types import OrgStatus

router = Router(tags=["Public Search"])

_P = "/search"


# ── Schemas ──────────────────────────────────────────────────────────────


class PublicDocResult(dict):
    """Lightweight serialization — we return plain dicts."""
    pass


# ── Search published documents ───────────────────────────────────────────


@router.get(
    f"{_P}/documents",
    response=dict,
    summary="Search published DID documents (public, no auth)",
)
def search_documents(
    request: HttpRequest,
    q: str = Query("", description="Search term (label, DID URI, org name)"),
    org_id: str = Query("", description="Filter by organization ID"),
    sort: str = Query("-updated_at", description="Sort field"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """
    Public search across all published DID documents.
    Returns paginated results with basic document info and DID URI.
    """
    from django.conf import settings

    qs = (
        DIDDocument.objects
        .filter(status=DocumentStatus.PUBLISHED)
        .select_related("organization", "owner", "current_version")
    )

    # Text search
    if q:
        qs = qs.filter(
            Q(label__icontains=q)
            | Q(organization__name__icontains=q)
            | Q(organization__slug__icontains=q)
            | Q(owner__full_name__icontains=q)
            | Q(owner__email__icontains=q)
        )

    # Org filter
    if org_id:
        try:
            qs = qs.filter(organization_id=UUID(org_id))
        except (ValueError, TypeError):
            pass

    # Sorting
    allowed_sorts = {
        "-updated_at", "-created_at", "created_at", "updated_at", "label", "-label",
    }
    if sort not in allowed_sorts:
        sort = "-updated_at"
    qs = qs.order_by(sort)

    # Pagination
    total = qs.count()
    total_pages = max(1, math.ceil(total / page_size))
    offset = (page - 1) * page_size
    docs = list(qs[offset:offset + page_size])

    domain = getattr(settings, "PLATFORM_DOMAIN", "localhost")

    results = []
    for doc in docs:
        org_slug = doc.organization.slug if doc.organization else ""
        owner_slug = doc.owner.email.split("@")[0] if doc.owner else ""

        did_uri = f"did:web:{domain}:{org_slug}:{owner_slug}:{doc.label}"

        results.append({
            "id": str(doc.id),
            "label": doc.label,
            "did_uri": did_uri,
            "status": doc.status,
            "organization_name": doc.organization.name if doc.organization else "",
            "organization_slug": org_slug,
            "owner_name": doc.owner.full_name if doc.owner else "",
            "version_count": doc.versions.count(),
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        })

    return {
        "results": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


# ── List approved organizations (for filter dropdown) ────────────────────


@router.get(
    f"{_P}/organizations",
    response=list,
    summary="List approved organizations (public, no auth)",
)
def list_organizations(request: HttpRequest):
    """
    Returns a simple list of approved organizations for the search filter.
    Only organizations that have at least one published document are included.
    """
    orgs = (
        Organization.objects
        .filter(
            status=OrgStatus.APPROVED,
            did_documents__status=DocumentStatus.PUBLISHED,
        )
        .distinct()
        .values("id", "name", "slug")
        .order_by("name")
    )

    return [
        {"id": str(o["id"]), "name": o["name"], "slug": o["slug"]}
        for o in orgs
    ]
