"""
DID Document assembler.

Builds a W3C DID Core v1.0 compliant JSON document from the
verification methods attached to a DIDDocument model instance.

DID URI format: did:web:<host>:<org_slug>:<owner_identifier>:<label>
"""

import datetime

from django.conf import settings


RELATIONSHIP_TYPES = [
    "authentication",
    "assertionMethod",
    "keyAgreement",
    "capabilityInvocation",
    "capabilityDelegation",
]

# Map (kty, crv) → alg per RFC 7518 / DID spec conventions
_ALG_MAP = {
    ("EC", "P-256"):   "ES256",
    ("EC", "P-384"):   "ES384",
    ("EC", "P-521"):   "ES512",
    ("EC", "secp256k1"): "ES256K",
    ("OKP", "Ed25519"): "EdDSA",
    ("OKP", "X25519"):  "ECDH-ES",
    ("RSA", None):      "RS256",
}


def build_did_uri(org_slug: str, owner_identifier: str, label: str) -> str:
    """
    Build the full DID URI for a did:web document.

    Format: did:web:<domain>:<org_slug>:<owner_identifier>:<label>
    Port colons become %3A per did:web spec.
    """
    domain = getattr(settings, "PLATFORM_DOMAIN", "localhost")
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

    Args:
        did_uri: Full DID URI
        verification_methods: QuerySet or list of DocumentVerificationMethod
            instances (with certificate and current_version loaded)
        service_endpoints: Optional service endpoint dicts

    Returns:
        W3C DID Core v1.0 compliant JSON dict
    """
    doc = {
        "@context": [
            "https://www.w3.org/ns/did/v1",
            "https://w3id.org/security/suites/jws-2020/v1",
        ],
        "id": did_uri,
    }

    # Build verificationMethod array
    vm_entries = []
    relationship_map = {r: [] for r in RELATIONSHIP_TYPES}

    for vm in verification_methods:
        if not vm.is_active:
            continue

        cert_version = vm.certificate.current_version
        if cert_version is None:
            continue

        method_full_id = f"{did_uri}#{vm.method_id_fragment}"

        # Enrich JWK with alg and use
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

    # Add non-empty relationship arrays
    for rel_type in RELATIONSHIP_TYPES:
        refs = relationship_map[rel_type]
        if refs:
            doc[rel_type] = refs

    # Service endpoints
    if service_endpoints:
        doc["service"] = _build_service_endpoints(did_uri, service_endpoints)

    return doc


def _enrich_jwk(jwk: dict, relationships: list[str]) -> dict:
    """
    Add 'alg' and 'use' to a JWK if not already present.

    - alg: inferred from (kty, crv) per RFC 7518
    - use: 'enc' if only keyAgreement, else 'sig'
    """
    enriched = dict(jwk)

    # Determine alg from key type and curve
    if "alg" not in enriched:
        kty = enriched.get("kty", "")
        crv = enriched.get("crv")
        alg = _ALG_MAP.get((kty, crv))
        if alg is None and kty == "RSA":
            alg = _ALG_MAP.get(("RSA", None))
        if alg:
            enriched["alg"] = alg

    # Determine use from relationships
    if "use" not in enriched:
        only_key_agreement = (
            relationships == ["keyAgreement"]
            or set(relationships) == {"keyAgreement"}
        )
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


def add_proof_to_document(did_document: dict, *, jws_signature: str) -> dict:
    """Attach a proof block to a DID document after signing."""
    doc = dict(did_document)
    doc["proof"] = {
        "type": "JsonWebSignature2020",
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "proofPurpose": "assertionMethod",
        "jws": jws_signature,
    }

    vm_list = doc.get("verificationMethod", [])
    if vm_list:
        doc["proof"]["verificationMethod"] = vm_list[0]["id"]

    return doc


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
    domain = getattr(settings, "PLATFORM_DOMAIN", "localhost")

    vc = {
        "@context": [
            "https://www.w3.org/2018/credentials/v1",
            "https://www.w3.org/ns/did/v1",
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
            "verificationMethodCount": len(
                did_document.get("verificationMethod", [])
            ),
            "publicationStatus": "published",
        },
    }

    # Add proof reference if the DID document has one
    proof = did_document.get("proof")
    if proof:
        vc["proof"] = {
            "type": proof.get("type", "JsonWebSignature2020"),
            "created": proof.get("created", published_at),
            "proofPurpose": "assertionMethod",
            "verificationMethod": proof.get("verificationMethod", ""),
            "jws": proof.get("jws", ""),
        }

    return vc