"""
SignServer integration.

Low-level HTTP client for the SignServer CE PlainSigner worker.
Sends raw bytes and receives a raw DER-encoded ECDSA signature.

The higher-level ecdsa-jcs-2019 proof construction lives in
``src.common.did.assembler``.

Configuration (environment / Django settings):
  SIGNSERVER_URL          — e.g. "http://signserver-node:8080" Internally
  SIGNSERVER_URL=http://signserver.qcdigitalhub.com/signserver
  SIGNSERVER_WORKER_NAME  — e.g. "PlainSigner"

If SIGNSERVER_URL is not set, a deterministic stub signature is returned
so the rest of the pipeline can be exercised in development.
"""

import structlog
from django.conf import settings

from src.common.exceptions import ValidationError

logger = structlog.get_logger(__name__)

# 64 zero-bytes → valid-length stub for P-256 raw r‖s
_STUB_RAW_SIG = b"\x00" * 64


# ── Public API ───────────────────────────────────────────────────────────


def _get_process_url() -> str:
    """Build the SignServer process endpoint URL from base URL."""
    base = settings.SIGNSERVER_URL or ""
    base = base.rstrip("/")
    if not base:
        return ""
    # Accept full URL if already includes /signserver/process
    if base.endswith("/signserver/process"):
        return base
    # Accept base URL with /signserver already
    if base.endswith("/signserver"):
        return f"{base}/process"
    # Plain base URL like http://signserver-node:8080
    return f"{base}/signserver/process"


def sign_bytes(data: bytes) -> bytes:
    """
    Send *data* to the SignServer PlainSigner and return the raw
    DER-encoded ECDSA signature bytes.

    The PlainSigner is configured with ``SHA256withECDSA`` so it will:
      1. Compute SHA-256 of *data*
      2. Sign the hash with ECDSA P-256
      3. Return the DER-encoded signature

    Args:
        data: Arbitrary bytes to sign (typically the ecdsa-jcs-2019
              hash-data: ``SHA-256(proofOptions) || SHA-256(document)``).

    Returns:
        Raw DER-encoded ECDSA signature bytes.

    Raises:
        ValidationError: If signing fails or SignServer returns an error.
    """
    url = _get_process_url()
    worker = settings.SIGNSERVER_WORKER_NAME

    if not url:
        logger.warning(
            "signserver_not_configured",
            hint="Set SIGNSERVER_URL in settings. Returning stub signature.",
        )
        return _STUB_RAW_SIG

    try:
        import requests as http_client

        logger.info(
            "signserver_signing",
            url=url,
            worker=worker,
            payload_bytes=len(data),
        )

        response = http_client.post(
            url,
            params={"workerName": worker},
            data=data,
            headers={"Content-Type": "application/octet-stream"},
            timeout=30,
        )

        if response.status_code != 200:
            logger.error(
                "signserver_http_error",
                status=response.status_code,
                body=response.text[:500],
            )
            raise ValidationError(
                f"SignServer returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

        sig_bytes = response.content
        if not sig_bytes:
            raise ValidationError("SignServer returned an empty signature.")

        logger.info("signserver_signed", sig_bytes_len=len(sig_bytes))
        return sig_bytes

    except ImportError:
        logger.error("signserver_requests_missing", hint="pip install requests")
        raise ValidationError("HTTP client (requests) not installed.") from None

    except Exception as e:
        if "ValidationError" in type(e).__name__:
            raise
        logger.error("signserver_failed", error=str(e), url=url)
        raise ValidationError(f"SignServer signing failed: {e}") from e


def health_check() -> dict:
    """
    Check SignServer availability.

    Returns:
        dict with "status" key ("ok", "unavailable", or "not_configured").
    """
    base = settings.SIGNSERVER_URL
    if not base:
        return {"status": "not_configured"}

    health_url = _build_url(base, "/signserver/healthcheck/signserverhealth")

    try:
        import requests as http_client

        r = http_client.get(health_url, timeout=5)
        if r.status_code == 200:
            return {"status": "ok", "response": r.text[:200]}
        return {"status": "unavailable", "http_status": r.status_code}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}

    # ── Internal helpers ─────────────────────────────────────────────────────


def _get_process_url() -> str:
    """Build the ``/signserver/process`` endpoint URL."""
    base = getattr(settings, "SIGNSERVER_URL", "") or ""
    if not base:
        return ""
    return _build_url(base, "/signserver/process")


def _build_url(base: str, path: str) -> str:
    """Normalise *base* and append *path*, avoiding double /signserver."""
    base = base.rstrip("/")
    if base.endswith("/signserver"):
        base = base[: -len("/signserver")]
    return f"{base}{path}"
