"""
SignServer integration.

Signs DID documents via the SignServer CE REST API.

Configuration (Django settings):
  SIGNSERVER_PROCESS_URL  = "http://signserver-node:8080/signserver/process"
  SIGNSERVER_WORKER_NAME  = "DIDDocumentSigner"

The SignServer worker should be a PlainSigner or JWS-capable worker
configured with the appropriate signing key (e.g., ECDSA P-256).

If SIGNSERVER_PROCESS_URL is not set or empty, a stub signature is
returned for development / testing.
"""

import json

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)

# Stub returned when SignServer is not configured
_STUB_JWS = "eyJhbGciOiJFUzI1NiJ9..STUB_SIGNATURE_DEV_MODE"


def sign_document(did_document: dict) -> str:
    """
    Sign a DID document and return a JWS detached signature.

    Args:
        did_document: The assembled DID document dict to sign.

    Returns:
        JWS compact serialization string (detached payload).

    Raises:
        ValidationError: If signing fails.
    """
    url = getattr(settings, "SIGNSERVER_PROCESS_URL", "")
    worker = getattr(settings, "SIGNSERVER_WORKER_NAME", "DIDDocumentSigner")

    if not url:
        logger.warning(
            "signserver_not_configured",
            hint="Set SIGNSERVER_PROCESS_URL in settings. Returning stub signature.",
        )
        return _STUB_JWS

    # Canonicalize: sorted keys, no whitespace — ensures deterministic signing
    canonical = json.dumps(did_document, sort_keys=True, separators=(",", ":"))

    try:
        import requests as http_client

        logger.info("signserver_signing", url=url, worker=worker, payload_bytes=len(canonical))

        response = http_client.post(
            url,
            data=canonical.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-SignServer-WorkerName": worker,
            },
            timeout=30,
        )

        if response.status_code != 200:
            logger.error(
                "signserver_http_error",
                status=response.status_code,
                body=response.text[:500],
            )
            from src.common.exceptions import ValidationError
            raise ValidationError(
                f"SignServer returned HTTP {response.status_code}: {response.text[:200]}"
            )

        jws = response.text.strip()
        if not jws:
            from src.common.exceptions import ValidationError
            raise ValidationError("SignServer returned an empty signature.")

        logger.info("signserver_signed", jws_length=len(jws))
        return jws

    except ImportError:
        logger.error("signserver_requests_missing", hint="pip install requests")
        from src.common.exceptions import ValidationError
        raise ValidationError("HTTP client (requests) not installed.")

    except Exception as e:
        if "ValidationError" in type(e).__name__:
            raise
        logger.error("signserver_failed", error=str(e), url=url)
        from src.common.exceptions import ValidationError
        raise ValidationError(f"SignServer signing failed: {e}")


def health_check() -> dict:
    """
    Check SignServer availability.

    Returns:
        dict with "status" key ("ok", "unavailable", or "not_configured").
    """
    url = getattr(settings, "SIGNSERVER_PROCESS_URL", "")
    if not url:
        return {"status": "not_configured"}

    # Derive the base URL from the process URL
    # e.g., http://signserver-node:8080/signserver/process → http://signserver-node:8080/signserver/healthcheck/signserverhealth
    base = url.rsplit("/process", 1)[0]
    health_url = f"{base}/healthcheck/signserverhealth"

    try:
        import requests as http_client
        r = http_client.get(health_url, timeout=5)
        if r.status_code == 200:
            return {"status": "ok", "response": r.text[:200]}
        return {"status": "unavailable", "http_status": r.status_code}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}