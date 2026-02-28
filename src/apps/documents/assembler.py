"""
DID Document assembler.

Builds a W3C DID Core v1.0 compliant JSON document from the
verification methods attached to a DIDDocument model instance.

Output:
{
  "@context": ["https://www.w3.org/ns/did/v1", ...],
  "id": "did:web:example.com:acme-corp:corporate-auth",
  "verificationMethod": [...],
  "authentication": [...],
  ...
}
"""

from django.conf import settings


RELATIONSHIP_TYPES = [
    "authentication",
    "assertionMethod",
    "keyAgreement",
    "capabilityInvocation",
    "capabilityDelegation",
]


def build_did_uri(org_slug: str, label: str) -> str:
    """
    Build the full DID URI for a did:web document.

    did:web uses colons as path separators:
      did:web:example.com:acme-corp:corporate-auth
    Port colons become %3A per did:web spec.
    """
    domain = getattr(settings, "PLATFORM_DOMAIN", "localhost")
    encoded_domain = domain.replace(":", "%3A")
    return f"did:web:{encoded_domain}:{org_slug}:{label}"


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

        vm_entry = {
            "id": method_full_id,
            "type": vm.method_type,
            "controller": did_uri,
            "publicKeyJwk": cert_version.public_key_jwk or {},
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
    import datetime

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