"""
Universal Registrar integration.

Manages DID documents via the DIF Universal Registrar REST API.

Configuration (Django settings):
  UNIVERSAL_REGISTRAR_URL = "http://uni-registrar-web:9080"

API endpoints used:
  POST /1.0/create      — Register a new DID
  POST /1.0/update      — Update an existing DID document
  POST /1.0/deactivate  — Deactivate a DID

The registrar's driver-did-web writes the did.json file to disk at
the configured basePath (shared via dids_volume with nginx).

If UNIVERSAL_REGISTRAR_URL is not set, stub responses are returned.
"""

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)


def create_did(did_document: dict) -> dict:
    """
    Register a new DID document via the Universal Registrar.

    Payload format (DIF Universal Registrar spec):
    {
      "jobId": null,
      "options": { "network": "mainnet" },
      "secret": {},
      "didDocument": { ... the assembled DID document ... }
    }

    For did:web, the driver writes the document to disk as did.json
    at the path derived from the DID URI segments.

    Args:
        did_document: Complete DID document dict with proof.

    Returns:
        Registrar response dict with didState.

    Raises:
        ValidationError: If registration fails.
    """
    url = _get_registrar_url()
    if not url:
        return _stub_response("create", did_document.get("id", ""))

    endpoint = f"{url}/1.0/create"
    payload = {
        "jobId": None,
        "options": {
            "network": "mainnet",
        },
        "secret": {},
        "didDocument": did_document,
    }

    return _post(endpoint, payload, operation="create")


def update_did(did_document: dict) -> dict:
    """
    Update an existing DID document via the Universal Registrar.

    Args:
        did_document: Updated DID document dict with proof.

    Returns:
        Registrar response dict with didState.
    """
    url = _get_registrar_url()
    if not url:
        return _stub_response("update", did_document.get("id", ""))

    endpoint = f"{url}/1.0/update"
    did_uri = did_document.get("id", "")

    payload = {
        "jobId": None,
        "did": did_uri,
        "options": {},
        "secret": {},
        "didDocumentOperation": ["setDidDocument"],
        "didDocument": [did_document],
    }

    return _post(endpoint, payload, operation="update")


def deactivate_did(did_uri: str) -> dict:
    """
    Deactivate a DID via the Universal Registrar.

    This marks the DID as deactivated. The did.json file may be updated
    to include a "deactivated" flag or removed entirely, depending on
    the driver configuration.

    Args:
        did_uri: The DID URI to deactivate (e.g., did:web:example.com:org:user:label)

    Returns:
        Registrar response dict with didState.
    """
    url = _get_registrar_url()
    if not url:
        return _stub_response("deactivate", did_uri)

    endpoint = f"{url}/1.0/deactivate"
    payload = {
        "jobId": None,
        "did": did_uri,
        "options": {},
        "secret": {},
    }

    return _post(endpoint, payload, operation="deactivate")


def health_check() -> dict:
    """
    Check Universal Registrar availability.

    Returns:
        dict with "status" key and optional properties/methods info.
    """
    url = _get_registrar_url()
    if not url:
        return {"status": "not_configured"}

    try:
        import requests as http_client

        # Check the properties endpoint
        r = http_client.get(f"{url}/1.0/properties", timeout=5)
        if r.status_code == 200:
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            return {
                "status": "ok",
                "methods": list(data.get("driver", {}).keys()) if isinstance(data.get("driver"), dict) else [],
            }
        return {"status": "unavailable", "http_status": r.status_code}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}


# ── Internal helpers ─────────────────────────────────────────────────────


def _get_registrar_url() -> str:
    """Get the Universal Registrar base URL from settings."""
    return getattr(settings, "UNIVERSAL_REGISTRAR_URL", "")


def _post(endpoint: str, payload: dict, operation: str) -> dict:
    """
    Send a POST request to the Universal Registrar.

    Validates the response and returns the parsed JSON.
    """
    try:
        import requests as http_client

        logger.info(
            "registrar_request",
            operation=operation,
            endpoint=endpoint,
            did=payload.get("did") or (payload.get("didDocument", {}).get("id") if isinstance(payload.get("didDocument"), dict) else ""),
        )

        response = http_client.post(
            endpoint,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

        # The registrar returns 200 or 201 on success
        if response.status_code not in (200, 201):
            logger.error(
                "registrar_http_error",
                operation=operation,
                status=response.status_code,
                body=response.text[:500],
            )
            from src.common.exceptions import ValidationError
            raise ValidationError(
                f"Registrar {operation} failed with HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

        result = response.json()

        # Check didState for errors
        did_state = result.get("didState", {})
        state = did_state.get("state", "")

        if state == "failed":
            reason = did_state.get("reason", "Unknown error")
            logger.error("registrar_did_state_failed", operation=operation, reason=reason)
            from src.common.exceptions import ValidationError
            raise ValidationError(f"Registrar {operation} failed: {reason}")

        if state in ("finished", "action"):
            logger.info(
                "registrar_success",
                operation=operation,
                state=state,
                did=did_state.get("did", ""),
            )

        return result

    except ImportError:
        logger.error("registrar_requests_missing", hint="pip install requests")
        from src.common.exceptions import ValidationError
        raise ValidationError("HTTP client (requests) not installed.")

    except Exception as e:
        if "ValidationError" in type(e).__name__:
            raise
        logger.error("registrar_failed", operation=operation, error=str(e))
        from src.common.exceptions import ValidationError
        raise ValidationError(f"Registrar {operation} failed: {e}")


def _stub_response(operation: str, did_uri: str) -> dict:
    """Return a stub response when registrar is not configured."""
    logger.warning(
        "registrar_not_configured",
        operation=operation,
        hint="Set UNIVERSAL_REGISTRAR_URL in settings. Returning stub response.",
    )
    return {
        "didState": {
            "state": "finished",
            "did": did_uri,
            "didDocument": {},
        },
        "_stub": True,
    }