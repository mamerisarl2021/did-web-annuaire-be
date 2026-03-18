"""
DID Document assembler.

Builds W3C DID Core v1.0 compliant JSON documents and creates
``ecdsa-jcs-2019`` Data Integrity proofs via SignServer.

DID URI format: did:web:<host>:<org_slug>:<owner_identifier>:<label>

Proof algorithm (W3C Data Integrity ECDSA Cryptosuites v1.0):
  1. Build proof options (type, cryptosuite, created, proofPurpose,
     verificationMethod) — *without* ``proofValue``.
  2. JCS-canonicalise proof options → bytes.
  3. JCS-canonicalise the unsigned document → bytes.
  4. hash_data = SHA-256(proof_options_bytes) || SHA-256(document_bytes)
  5. Send hash_data to SignServer PlainSigner (SHA256withECDSA).
  6. Convert the returned DER signature to raw r||s (64 bytes for P-256).
  7. Multibase-encode: ``'z' + base58btc(raw_sig)``  — or —
     ``'u' + base64url_no_pad(raw_sig)``.
     We use ``'z' + base58btc`` which is the default in the spec.
  8. Set ``proof.proofValue`` and attach proof to the document.
"""

import base64
import datetime
import hashlib
import json

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

RELATIONSHIP_TYPES = [
    "authentication",
    "assertionMethod",
    "keyAgreement",
    "capabilityInvocation",
    "capabilityDelegation",
]

DID_CORE_CONTEXT = "https://www.w3.org/ns/did/v1"
DATA_INTEGRITY_CONTEXT = "https://w3id.org/security/data-integrity/v2"
JWS_2020_CONTEXT = "https://w3id.org/security/suites/jws-2020/v1"

# Map (kty, crv) → alg per RFC 7518 / DID spec conventions
_ALG_MAP = {
    ("EC", "P-256"): "ES256",
    ("EC", "P-384"): "ES384",
    ("EC", "P-521"): "ES512",
    ("EC", "secp256k1"): "ES256K",
    ("OKP", "Ed25519"): "EdDSA",
    ("OKP", "X25519"): "ECDH-ES",
    ("RSA", None): "RS256",
}


# ═════════════════════════════════════════════════════════════════════════
#  DID Document Assembly
# ═════════════════════════════════════════════════════════════════════════


def build_did_uri(org_slug: str, owner_identifier: str, label: str) -> str:
    """
    Build the full DID URI for a did:web document.

    Format: did:web:<domain>:<org_slug>:<owner_identifier>:<label>
    Port colons become %3A per did:web spec.
    """
    domain = settings.PLATFORM_DOMAIN_WITHOUT_SCHEME
    encoded_domain = domain.replace(":", "%3A")
    return f"did:web:{encoded_domain}:{org_slug}:{owner_identifier}:{label}"


def assemble_did_document(
    *,
    did_uri: str,
    verification_methods: list,
    service_endpoints: list[dict] | None = None,
) -> dict:
    """
    Assemble a complete DID document from verification method records.

    The ``@context`` includes the JWS-2020 suite (for the
    ``JsonWebKey2020`` verification method type).  The Data Integrity
    context is added later when a proof is attached.

    Args:
        did_uri: Full DID URI.
        verification_methods: QuerySet or list of
            ``DocumentVerificationMethod`` instances.
        service_endpoints: Optional service endpoint dicts.

    Returns:
        W3C DID Core v1.0 compliant JSON dict (unsigned).
    """
    doc: dict = {
        "@context": [
            DID_CORE_CONTEXT,
            JWS_2020_CONTEXT,
        ],
        "id": did_uri,
    }

    # Build verificationMethod array
    vm_entries: list[dict] = []
    relationship_map: dict[str, list[str]] = {r: [] for r in RELATIONSHIP_TYPES}

    for vm in verification_methods:
        if not vm.is_active:
            continue

        cert_version = vm.certificate.current_version
        if cert_version is None:
            continue

        method_full_id = f"{did_uri}#{vm.method_id_fragment}"

        jwk = _enrich_jwk(
            cert_version.public_key_jwk or {},
            vm.relationship_list,
        )

        vm_entry = {
            "id": method_full_id,
            "type": vm.method_type,
            "controller": did_uri,
            "publicKeyJwk": jwk,
        }
        vm_entries.append(vm_entry)

        for rel in vm.relationship_list:
            if rel in relationship_map:
                relationship_map[rel].append(method_full_id)

    doc["verificationMethod"] = vm_entries

    for rel_type in RELATIONSHIP_TYPES:
        refs = relationship_map[rel_type]
        if refs:
            doc[rel_type] = refs

    if service_endpoints:
        doc["service"] = _build_service_endpoints(did_uri, service_endpoints)

    return doc


# ═════════════════════════════════════════════════════════════════════════
#  ecdsa-jcs-2019  —  Data Integrity Proof Creation
# ═════════════════════════════════════════════════════════════════════════


def create_proof(
    did_document: dict,
    *,
    verification_method_id: str | None = None,
) -> dict:
    """
    Create an ``ecdsa-jcs-2019`` Data Integrity proof for *did_document*.

    This is the main entry point for signing.  It:
      1. Builds the proof-options object.
      2. JCS-canonicalises both proof options and the document.
      3. Computes ``hash_data = SHA-256(options) || SHA-256(doc)``.
      4. Sends *hash_data* to SignServer's PlainSigner.
      5. Converts the DER response to raw r||s.
      6. Multibase-encodes the raw signature.
      7. Returns the complete proof dict (ready to attach).

    Args:
        did_document: The assembled (unsigned) DID document dict.
        verification_method_id: Full URI of the verification method
            that can verify this signature.  Falls back to the first
            ``assertionMethod`` or ``verificationMethod`` in the doc.

    Returns:
        A proof dict suitable for ``add_proof_to_document()``.

    Raises:
        ValidationError: If signing fails.
    """
    from src.integrations.signserver import sign_bytes

    # ── 1. Resolve verificationMethod for the proof ─────────────────
    if not verification_method_id:
        verification_method_id = _resolve_verification_method(did_document)

    # ── 2. Build proof options (without proofValue) ─────────────────
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    proof_options = {
        "type": "DataIntegrityProof",
        "cryptosuite": "ecdsa-jcs-2019",
        "proofPurpose": "assertionMethod",
        "verificationMethod": verification_method_id,
        "created": now,
    }

    # ── 3. JCS-canonicalise both objects ────────────────────────────
    proof_options_bytes = _jcs_canonicalize(proof_options)
    document_bytes = _jcs_canonicalize(did_document)

    # ── 4. Build hash_data ──────────────────────────────────────────
    hash_data = (
        hashlib.sha256(proof_options_bytes).digest()
        + hashlib.sha256(document_bytes).digest()
    )
    # hash_data is 64 bytes (two SHA-256 digests concatenated)

    logger.info(
        "proof_hash_data",
        proof_options_len=len(proof_options_bytes),
        document_len=len(document_bytes),
        hash_data_hex=hash_data[:16].hex() + "...",
    )

    # ── 5. Sign via SignServer ──────────────────────────────────────
    der_signature = sign_bytes(hash_data)

    # ── 6. Convert DER → raw r||s ──────────────────────────────────
    raw_sig = _der_to_raw_ecdsa(der_signature, key_size=32)

    # ── 7. Multibase-encode (base64url-no-pad, prefix 'u') ─────────
    proof_value = _multibase_encode(raw_sig)

    # ── 8. Complete the proof ───────────────────────────────────────
    proof_options["proofValue"] = proof_value

    logger.info(
        "proof_created",
        cryptosuite="ecdsa-jcs-2019",
        proof_value_len=len(proof_value),
        verification_method=verification_method_id,
    )

    return proof_options


def add_proof_to_document(did_document: dict, proof: dict) -> dict:
    """
    Attach a Data Integrity proof to a DID document.

    Ensures the ``@context`` includes the Data Integrity v2 context
    required to interpret ``DataIntegrityProof`` objects.

    Args:
        did_document: The unsigned DID document dict.
        proof: A proof dict from ``create_proof()``.

    Returns:
        A *new* dict — the original is not mutated.
    """
    doc = dict(did_document)

    # Ensure Data Integrity context is present
    ctx = list(doc.get("@context", []))
    if DATA_INTEGRITY_CONTEXT not in ctx:
        ctx.append(DATA_INTEGRITY_CONTEXT)
    doc["@context"] = ctx

    doc["proof"] = proof
    return doc


def sign_and_attach_proof(
    did_document: dict,
    *,
    verification_method_id: str | None = None,
) -> tuple[dict, str]:
    """
    Convenience wrapper: create an ecdsa-jcs-2019 proof and attach it.

    Args:
        did_document: Unsigned DID document.
        verification_method_id: Optional VM URI for the proof.

    Returns:
        Tuple of (signed_document, proof_value_string).
    """
    proof = create_proof(
        did_document,
        verification_method_id=verification_method_id,
    )
    signed = add_proof_to_document(did_document, proof)
    return signed, proof.get("proofValue", "")


# ═════════════════════════════════════════════════════════════════════════
#  Verifiable Credential Builder
# ═════════════════════════════════════════════════════════════════════════


def build_verifiable_credential(
    *,
    did_uri: str,
    did_document: dict,
    org_name: str,
    owner_name: str,
    label: str,
    version: int,
    published_at: str,
) -> dict:
    """
    Build a W3C Verifiable Credential (VC) for a published DID document.

    The VC attests that the organization has published this DID document
    through the AnnuaireDID platform.
    """
    domain = getattr(settings, "PLATFORM_DOMAIN_WITHOUT_SCHEME", "localhost")

    vc: dict = {
        "@context": [
            "https://www.w3.org/2018/credentials/v1",
            DID_CORE_CONTEXT,
        ],
        "type": ["VerifiableCredential", "DIDPublicationCredential"],
        "issuer": {
            "id": f"did:web:{domain.replace(':', '%3A')}",
            "name": "AnnuaireDID Platform",
        },
        "issuanceDate": published_at,
        "credentialSubject": {
            "id": did_uri,
            "type": "DIDDocument",
            "organization": org_name,
            "owner": owner_name,
            "label": label,
            "version": version,
            "verificationMethodCount": len(did_document.get("verificationMethod", [])),
            "publicationStatus": "published",
        },
    }

    # Mirror the proof from the signed DID document
    proof = did_document.get("proof")
    if proof:
        vc["proof"] = {
            "type": proof.get("type", "DataIntegrityProof"),
            "cryptosuite": proof.get("cryptosuite", "ecdsa-jcs-2019"),
            "created": proof.get("created", published_at),
            "proofPurpose": "assertionMethod",
            "verificationMethod": proof.get("verificationMethod", ""),
            "proofValue": proof.get("proofValue", ""),
        }

    return vc


# ═════════════════════════════════════════════════════════════════════════
#  Internal Helpers
# ═════════════════════════════════════════════════════════════════════════


def _enrich_jwk(jwk: dict, relationships: list[str]) -> dict:
    """
    Add 'alg' and 'use' to a JWK if not already present.

    - alg: inferred from (kty, crv) per RFC 7518
    - use: 'enc' if only keyAgreement, else 'sig'
    """
    enriched = dict(jwk)

    if "alg" not in enriched:
        kty = enriched.get("kty", "")
        crv = enriched.get("crv")
        alg = _ALG_MAP.get((kty, crv))
        if alg is None and kty == "RSA":
            alg = _ALG_MAP.get(("RSA", None))
        if alg:
            enriched["alg"] = alg

    if "use" not in enriched:
        only_key_agreement = relationships == ["keyAgreement"] or set(
            relationships
        ) == {"keyAgreement"}
        enriched["use"] = "enc" if only_key_agreement else "sig"

    return enriched


def _build_service_endpoints(did_uri: str, endpoints: list[dict]) -> list[dict]:
    services = []
    for ep in endpoints:
        service = {
            "id": f"{did_uri}#{ep.get('id', f'service-{len(services) + 1}')}",
            "type": ep.get("type", "LinkedDomains"),
            "serviceEndpoint": ep.get("endpoint", ep.get("serviceEndpoint", "")),
        }
        services.append(service)
    return services


def _resolve_verification_method(did_document: dict) -> str:
    """
    Find the best verificationMethod ID for the proof.

    Priority: first assertionMethod ref, then first verificationMethod entry.

    Raises:
        ValidationError: If no verification method is found.
    """
    from src.common.exceptions import ValidationError

    # Try assertionMethod refs first
    assertion_refs = did_document.get("assertionMethod", [])
    if assertion_refs:
        return assertion_refs[0]

    # Fall back to first verificationMethod entry
    vm_list = did_document.get("verificationMethod", [])
    if vm_list:
        return vm_list[0]["id"]

    raise ValidationError(
        "Cannot sign: no verificationMethod found in the DID document."
    )


def _jcs_canonicalize(obj: dict) -> bytes:
    """
    JSON Canonicalization Scheme (RFC 8785).

    For DID documents (which contain only strings, arrays, objects, and
    occasionally integers — no floats, no special unicode) Python's
    ``json.dumps(sort_keys=True)`` produces output identical to JCS.

    For full RFC 8785 compliance install the ``jcs`` package::

        pip install jcs

    and this function will use it automatically.
    """
    try:
        import jcs as _jcs  # type: ignore[import-untyped]

        return _jcs.canonicalize(obj)
    except ImportError:
        return json.dumps(
            obj,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


def _der_to_raw_ecdsa(der_bytes: bytes, *, key_size: int = 32) -> bytes:
    """
    Convert a DER-encoded ECDSA signature to raw ``r || s`` format.

    DER layout::

        0x30 <total_len>
            0x02 <r_len> <r_bytes...>
            0x02 <s_len> <s_bytes...>

    For P-256, *key_size* = 32 → output is exactly 64 bytes.

    If the input does not start with 0x30 (DER SEQUENCE tag), it is
    assumed to already be in raw format and returned as-is (padded or
    truncated to ``2 * key_size``).

    Args:
        der_bytes: DER-encoded signature from SignServer.
        key_size: Byte length of each integer (32 for P-256).

    Returns:
        Raw ``r || s`` concatenation (``2 * key_size`` bytes).

    Raises:
        ValueError: If the DER structure is malformed.
    """
    expected_raw_len = 2 * key_size

    # If it doesn't start with 0x30, assume raw already
    if not der_bytes or der_bytes[0] != 0x30:
        if len(der_bytes) == expected_raw_len:
            return der_bytes
        raise ValueError(
            f"Expected DER (0x30...) or raw ({expected_raw_len} bytes), "
            f"got {len(der_bytes)} bytes starting with "
            f"0x{der_bytes[0]:02x}"
            if der_bytes
            else "empty"
        )

    idx = 2  # skip 0x30 and total length byte

    # Handle multi-byte length (for signatures > 127 bytes)
    if der_bytes[1] & 0x80:
        num_len_bytes = der_bytes[1] & 0x7F
        idx += num_len_bytes

    # Parse r
    if der_bytes[idx] != 0x02:
        raise ValueError(
            f"Expected INTEGER tag (0x02) for r, got 0x{der_bytes[idx]:02x}"
        )
    idx += 1
    r_len = der_bytes[idx]
    idx += 1
    r_bytes = der_bytes[idx : idx + r_len]
    idx += r_len

    # Parse s
    if der_bytes[idx] != 0x02:
        raise ValueError(
            f"Expected INTEGER tag (0x02) for s, got 0x{der_bytes[idx]:02x}"
        )
    idx += 1
    s_len = der_bytes[idx]
    idx += 1
    s_bytes = der_bytes[idx : idx + s_len]

    # Strip leading zero-padding (DER uses signed integers)
    r_int = int.from_bytes(r_bytes, "big")
    s_int = int.from_bytes(s_bytes, "big")

    r_raw = r_int.to_bytes(key_size, "big")
    s_raw = s_int.to_bytes(key_size, "big")

    return r_raw + s_raw


def _multibase_encode(raw_bytes: bytes) -> str:
    """
    Multibase-encode using base64url-no-pad (prefix ``u``).

    This is one of the two encodings the ecdsa-jcs-2019 spec allows.
    The other is base58btc (prefix ``z``).  We use base64url because it
    has no external dependency and is widely supported.

    Args:
        raw_bytes: The raw signature bytes to encode.

    Returns:
        Multibase string like ``"u<base64url_no_pad>"``.
    """
    encoded = base64.urlsafe_b64encode(raw_bytes).rstrip(b"=").decode("ascii")
    return f"u{encoded}"
