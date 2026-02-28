"""
Certificate extraction service.

Calls the ecdsa-extractor.jar via subprocess to extract JWK and metadata
from X.509 certificates. Uses BouncyCastle under the hood for reliable
handling of named curve parameters.

Configuration:
    JWK_EXTRACTOR_JAR — path to the fat JAR. Set in Django settings.
    JWK_EXTRACTOR_JAVA — path to java binary (default: 'java').
"""

import json
import subprocess
import tempfile

import structlog
from django.conf import settings

from src.common.exceptions import ValidationError

logger = structlog.get_logger(__name__)

DEFAULT_JAVA_BIN = "java"
DEFAULT_JAR_PATH = "/opt/ecdsa-extractor.jar"


def _get_java_bin() -> str:
    return getattr(settings, "JWK_EXTRACTOR_JAVA", DEFAULT_JAVA_BIN)


def _get_jar_path() -> str:
    return getattr(settings, "JWK_EXTRACTOR_JAR", DEFAULT_JAR_PATH)


def extract_jwk(*, cert_pem_bytes: bytes, p12_password: str | None = None) -> dict:
    """
    Extract JWK from a certificate file.

    Args:
        cert_pem_bytes: raw bytes of the PEM/DER/P12 file
        p12_password: password for PKCS#12 keystores (optional)

    Returns:
        dict — the JWK as a Python dict

    Raises:
        ValidationError on extraction failure.
    """
    result = _run_extractor("--jwk", cert_pem_bytes, p12_password)
    try:
        return json.loads(result)
    except json.JSONDecodeError as e:
        raise ValidationError(f"Failed to parse JWK output: {e}")


def extract_metadata(*, cert_pem_bytes: bytes, p12_password: str | None = None) -> dict:
    """
    Extract full metadata from a certificate file.

    Returns:
        dict with keys:
            subject_dn, issuer_dn, serial_number,
            not_valid_before (ISO), not_valid_after (ISO),
            key_type, key_curve (EC only), key_size (RSA only),
            fingerprint_sha256,
            public_key_jwk (dict)

    Raises:
        ValidationError on extraction failure.
    """
    result = _run_extractor("--metadata", cert_pem_bytes, p12_password)
    try:
        return json.loads(result)
    except json.JSONDecodeError as e:
        raise ValidationError(f"Failed to parse metadata output: {e}")


def _run_extractor(mode: str, cert_bytes: bytes, p12_password: str | None = None) -> str:
    """
    Write cert to a temp file and call the JAR.
    """
    java_bin = _get_java_bin()
    jar_path = _get_jar_path()

    with tempfile.NamedTemporaryFile(suffix=".pem", delete=True) as tmp:
        tmp.write(cert_bytes)
        tmp.flush()

        cmd = [java_bin, "-jar", jar_path, mode]
        if p12_password is not None:
            cmd.extend(["--p12-password", p12_password])
        cmd.append(tmp.name)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            raise ValidationError(
                f"Java binary not found at '{java_bin}'. "
                "Ensure JDK is installed and JWK_EXTRACTOR_JAVA is set."
            )
        except subprocess.TimeoutExpired:
            raise ValidationError("Certificate extraction timed out (30s).")

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown error"
            logger.error(
                "cert_extraction_failed",
                mode=mode,
                return_code=result.returncode,
                stderr=error_msg,
            )
            raise ValidationError(f"Certificate extraction failed: {error_msg}")

        return result.stdout.strip()