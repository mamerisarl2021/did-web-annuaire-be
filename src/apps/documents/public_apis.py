import math
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest
from ninja import Query, Router
from ninja.throttling import AnonRateThrottle

from src.apps.documents.selectors import search_published_documents
from src.apps.organizations.models import Organization
from src.apps.documents.models import DocumentStatus
from src.common.types import OrgStatus

public_throttle = AnonRateThrottle("60/m")

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
    throttle=public_throttle,
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
    Recherche publique dans tous les documents DID publiés.
    Retourne des résultats paginés avec les informations de base du document et l'URI DID.
    """
    docs, total = search_published_documents(
        q=q,
        org_id=org_id,
        sort=sort,
        page=page,
        page_size=page_size,
    )

    total_pages = max(1, math.ceil(total / page_size))

    domain = settings.PLATFORM_DOMAIN
    domain = urlparse(domain).netloc

    results = []
    for doc in docs:
        org_slug = doc.organization.slug if doc.organization else ""
        owner_slug = doc.owner.email.split("@")[0] if doc.owner else ""
        did_uri = f"did:web:{domain}:{org_slug}:{owner_slug}:{doc.label}"

        results.append(
            {
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
            }
        )

    return {
        "results": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }



@router.get(
    f"{_P}/organizations",
    response=list,
    summary="List approved organizations (public, no auth)",
    throttle=public_throttle,
)
def list_organizations(request: HttpRequest):
    """
    Returns a simple list of approved organizations for the search filter.
    Only organizations that have at least one published document are included.
    """
    orgs = (
        Organization.objects.filter(
            status=OrgStatus.APPROVED,
            did_documents__status=DocumentStatus.PUBLISHED,
        )
        .distinct()
        .values("id", "name", "slug")
        .order_by("name")
    )

    return [{"id": str(o["id"]), "name": o["name"], "slug": o["slug"]} for o in orgs]


# ── DID Resolver proxy ──────────────────────────────────────────────────


@router.get(
    "/resolve",
    response=dict,
    summary="Resolve a DID via the Universal Resolver (public, no auth)",
    throttle=public_throttle,
)
def resolve_did_proxy(
        request: HttpRequest,
        did: str = Query(..., description="The fully-qualified DID URI to resolve"),
):
    """
    Proxy DID resolution through the backend to the configured Universal Resolver.

    Returns the full W3C DID Resolution Result:
      {
        "didDocument": { ... },
        "didResolutionMetadata": { ... },
        "didDocumentMetadata": { ... }
      }
    """
    from src.integrations.resolver import resolve_did

    return resolve_did(did)
