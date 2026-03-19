"""
Universal Resolver integration.

Resolves DID documents via the DIF Universal Resolver REST API.

Configuration (Django settings):
  UNIVERSAL_RESOLVER_URL = "https://annuairedid-be.qcdigitalhub.com/resolver"

API endpoint used:
  GET /1.0/identifiers/{did}

The resolver returns a W3C DID Resolution Result:
  {
    "didDocument": { ... },
    "didResolutionMetadata": { "contentType": "application/did+json", ... },
    "didDocumentMetadata": { ... }
  }

If UNIVERSAL_RESOLVER_URL is not set, a NotFoundError is raised.
"""

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)


def resolve_did(did_uri: str) -> dict:
    """
    Resolve a DID identifier via the Universal Resolver.

    Args:
        did_uri: The fully-qualified DID to resolve
                 (e.g., 'did:web:annuairedid-be.qcdigitalhub.com:eliptik-corporation:alice:passport').

    Returns:
        Full DID Resolution Result dict that contains:
          - didDocument: the resolved DID document
          - didResolutionMetadata: resolution metadata (contentType, error, etc.)
          - didDocumentMetadata: document-level metadata

    Raises:
        ValidationError: if the resolver is unavailable or returns an error.
        NotFoundError:   if the DID cannot be resolved (meta.error is set).
    """
    url = _get_resolver_url()
    if not url:
        from src.common.exceptions import ValidationError
        raise ValidationError("Universal Resolver is not configured. Set UNIVERSAL_RESOLVER_URL.")

    import urllib.parse
    encoded = urllib.parse.quote(did_uri, safe="")
    endpoint = f"{url}/1.0/identifiers/{encoded}"

    return _get(endpoint, did_uri=did_uri)


def health_check() -> dict:
    """
    Check Universal Resolver availability.

    Returns:
        dict with "status" key and optional methods info.
    """
    url = _get_resolver_url()
    if not url:
        return {"status": "not_configured"}

    try:
        import requests as http_client

        r = http_client.get(f"{url}/1.0/methods", timeout=5)
        if r.status_code == 200:
            return {"status": "ok"}
        return {"status": "unavailable", "http_status": r.status_code}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}


# ── Internal helpers ─────────────────────────────────────────────────────


def _get_resolver_url() -> str:
    """Get the Universal Resolver base URL from settings, stripping trailing slashes."""
    url = getattr(settings, "UNIVERSAL_RESOLVER_URL", "")
    return url.rstrip("/") if url else ""


def _get(endpoint: str, did_uri: str) -> dict:
    """
    Send a GET request to the Universal Resolver and return parsed JSON.

    Raises ValidationError or NotFoundError based on the resolver response.
    """
    try:
        import requests as http_client

        logger.info("resolver_request", did=did_uri, endpoint=endpoint)

        response = http_client.get(
            endpoint,
            headers={"Accept": "application/did+json, application/json"},
            timeout=15,
        )

        if response.status_code == 404:
            from src.common.exceptions import NotFoundError
            raise NotFoundError(f"DID not found: {did_uri}")

        if response.status_code not in (200, 201):
            logger.error(
                "resolver_http_error",
                status=response.status_code,
                body=response.text[:500],
                did=did_uri,
            )
            from src.common.exceptions import ValidationError
            raise ValidationError(
                f"Resolver returned HTTP {response.status_code}: {response.text[:200]}"
            )

        result = response.json()

        # The resolver may return either:
        #   (a) W3C DID Resolution Result: { "didDocument": {...}, "didResolutionMetadata": {...}, ... }
        #   (b) Raw DID document directly: { "id": "did:web:...", "verificationMethod": [...], ... }
        # Normalize (b) into the W3C wrapper format.
        if "didDocument" not in result and result.get("id", "").startswith("did:"):
            logger.info(
                "resolver_normalizing_flat_response",
                did=did_uri,
                hint="Resolver returned raw DID document; wrapping in W3C format.",
            )
            result = {
                "didDocument": result,
                "didResolutionMetadata": {"contentType": "application/did+json"},
                "didDocumentMetadata": {},
            }

        # Check didResolutionMetadata for error field (per W3C spec)
        meta = result.get("didResolutionMetadata", {})
        if meta.get("error"):
            error_code = meta["error"]
            logger.warning("resolver_did_error", did=did_uri, error=error_code)
            from src.common.exceptions import NotFoundError
            raise NotFoundError(f"DID resolution error: {error_code}")

        logger.info(
            "resolver_success",
            did=did_uri,
            has_document=bool(result.get("didDocument")),
        )

        return result

    except ImportError:
        logger.error("resolver_requests_missing", hint="pip install requests")
        from src.common.exceptions import ValidationError
        raise ValidationError("HTTP client (requests) not installed.")

    except Exception as e:
        if type(e).__name__ in ("ValidationError", "NotFoundError"):
            raise
        logger.error("resolver_failed", did=did_uri, error=str(e))
        from src.common.exceptions import ValidationError
        raise ValidationError(f"Resolver failed: {e}")
