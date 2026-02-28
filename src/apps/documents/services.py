"""
DID Document services (write operations).

Lifecycle:
  ORG_MEMBER: DRAFT → PENDING_REVIEW → APPROVED → PUBLISHED → DEACTIVATED
                                      → REJECTED → re-edit → DRAFT
  ORG_ADMIN:  DRAFT → PUBLISHED (direct, skips review)
              DRAFT → DEACTIVATED (if published)
"""

import json
import re

import structlog
from django.db import transaction
from django.utils import timezone

from src.apps.documents.assembler import (
    add_proof_to_document,
    assemble_did_document,
    build_did_uri,
    build_verifiable_credential,
)
from src.apps.documents.models import (
    DIDDocument,
    DIDDocumentVersion,
    DocumentStatus,
    DocumentVerificationMethod,
    VerificationRelationship,
)
from src.apps.users.models import User
from src.common.exceptions import ConflictError, NotFoundError, ValidationError

logger = structlog.get_logger(__name__)

LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,118}[a-z0-9]$")


def _did_uri_for(doc: DIDDocument) -> str:
    """Build the DID URI from a document's relations."""
    return build_did_uri(
        org_slug=doc.organization.slug,
        owner_identifier=doc.owner_identifier,
        label=doc.label,
    )


# ── Create ───────────────────────────────────────────────────────────────


@transaction.atomic
def create_document(
    *,
    organization,
    label: str,
    created_by: User,
    verification_methods: list[dict] | None = None,
    service_endpoints: list[dict] | None = None,
) -> DIDDocument:
    from src.apps.documents.selectors import document_label_exists

    label = label.strip().lower()
    if not label:
        raise ValidationError("Document label is required.")
    if not LABEL_RE.match(label):
        raise ValidationError(
            "Label must be 2-120 chars, lowercase alphanumeric and hyphens, "
            "starting and ending with a letter or digit."
        )
    if document_label_exists(
        organization_id=organization.id, owner_id=created_by.id, label=label,
    ):
        raise ConflictError(f"Label '{label}' already exists for you in this organization.")

    doc = DIDDocument.objects.create(
        organization=organization,
        label=label,
        status=DocumentStatus.DRAFT,
        owner=created_by,
        created_by=created_by,
    )

    if verification_methods:
        _create_verification_methods(
            document=doc, organization=organization,
            vm_specs=verification_methods, user=created_by,
        )

    did_uri = _did_uri_for(doc)
    did_json = _assemble_from_db(doc, did_uri, service_endpoints)
    doc.draft_content = did_json
    doc.save(update_fields=["draft_content", "updated_at"])

    _log("DOC_CREATED", created_by, doc,
         f"DID document '{label}' created. URI: {did_uri}")

    logger.info("document_created", doc_id=str(doc.id), label=label)
    return doc


# ── Update draft ─────────────────────────────────────────────────────────


@transaction.atomic
def update_draft(
    *,
    document: DIDDocument,
    updated_by: User,
    verification_methods: list[dict] | None = None,
    service_endpoints: list[dict] | None = None,
) -> DIDDocument:
    editable = {DocumentStatus.DRAFT, DocumentStatus.REJECTED, DocumentStatus.PUBLISHED}
    if document.status not in editable:
        raise ValidationError(f"Cannot edit a {document.status} document.")

    if document.status == DocumentStatus.REJECTED:
        document.status = DocumentStatus.DRAFT
        document.reviewed_by = None
        document.reviewed_at = None
        document.review_comment = ""

    if verification_methods is not None:
        DocumentVerificationMethod.objects.filter(document=document).delete()
        _create_verification_methods(
            document=document, organization=document.organization,
            vm_specs=verification_methods, user=updated_by,
        )

    did_uri = _did_uri_for(document)
    did_json = _assemble_from_db(document, did_uri, service_endpoints)
    document.draft_content = did_json

    document.save(update_fields=[
        "draft_content", "status", "reviewed_by",
        "reviewed_at", "review_comment", "updated_at",
    ])

    _log("DOC_DRAFT_UPDATED", updated_by, document,
         f"Draft updated for '{document.label}'.")

    return document


# ── Add / remove verification methods ───────────────────────────────────


@transaction.atomic
def add_verification_method(
    *,
    document: DIDDocument,
    certificate_id,
    method_id_fragment: str,
    relationships: list[str],
    method_type: str = "JsonWebKey2020",
    added_by: User,
) -> DocumentVerificationMethod:
    _require_editable(document)

    from src.apps.certificates.selectors import get_certificate_by_id

    cert = get_certificate_by_id(cert_id=certificate_id)
    if cert is None or str(cert.organization_id) != str(document.organization_id):
        raise NotFoundError("Certificate not found in this organization.")
    if cert.status != "ACTIVE":
        raise ValidationError("Cannot use a revoked or expired certificate.")

    if DocumentVerificationMethod.objects.filter(
        document=document, method_id_fragment=method_id_fragment
    ).exists():
        raise ConflictError(f"Fragment '#{method_id_fragment}' already exists.")

    _validate_relationships(relationships)

    vm = DocumentVerificationMethod.objects.create(
        document=document,
        certificate=cert,
        method_id_fragment=method_id_fragment,
        method_type=method_type,
        relationships=",".join(relationships),
    )

    _reassemble_draft(document)
    return vm


@transaction.atomic
def remove_verification_method(*, document: DIDDocument, vm_id, removed_by: User):
    _require_editable(document)
    try:
        vm = DocumentVerificationMethod.objects.get(id=vm_id, document=document)
    except DocumentVerificationMethod.DoesNotExist:
        raise NotFoundError("Verification method not found.")
    vm.delete()
    _reassemble_draft(document)


# ── Submit for review ────────────────────────────────────────────────────


@transaction.atomic
def submit_for_review(*, document: DIDDocument, submitted_by: User) -> DIDDocument:
    if document.status != DocumentStatus.DRAFT:
        raise ValidationError(f"Only DRAFT documents can be submitted. Status: {document.status}.")

    active_vms = DocumentVerificationMethod.objects.filter(
        document=document, is_active=True
    ).count()
    if active_vms == 0:
        raise ValidationError("Add at least one verification method before submitting.")

    document.status = DocumentStatus.PENDING_REVIEW
    document.submitted_by = submitted_by
    document.submitted_at = timezone.now()
    document.save(update_fields=["status", "submitted_by", "submitted_at", "updated_at"])

    _log("DOC_SUBMITTED", submitted_by, document,
         f"Document '{document.label}' submitted for review.")
    return document


# ── Approve / reject ────────────────────────────────────────────────────


@transaction.atomic
def approve_document(
    *, document: DIDDocument, approved_by: User, comment: str = "",
) -> DIDDocument:
    if document.status != DocumentStatus.PENDING_REVIEW:
        raise ValidationError(f"Only PENDING_REVIEW documents can be approved.")
    if document.owner_id == approved_by.id:
        raise ValidationError("You cannot approve your own document.")

    document.status = DocumentStatus.APPROVED
    document.reviewed_by = approved_by
    document.reviewed_at = timezone.now()
    document.review_comment = comment
    document.save(update_fields=[
        "status", "reviewed_by", "reviewed_at", "review_comment", "updated_at",
    ])

    _log("DOC_APPROVED", approved_by, document,
         f"Document '{document.label}' approved.{f' Comment: {comment}' if comment else ''}")
    return document


@transaction.atomic
def reject_document(
    *, document: DIDDocument, rejected_by: User, reason: str = "",
) -> DIDDocument:
    if document.status != DocumentStatus.PENDING_REVIEW:
        raise ValidationError(f"Only PENDING_REVIEW documents can be rejected.")
    if document.owner_id == rejected_by.id:
        raise ValidationError("You cannot reject your own document.")

    document.status = DocumentStatus.REJECTED
    document.reviewed_by = rejected_by
    document.reviewed_at = timezone.now()
    document.review_comment = reason
    document.save(update_fields=[
        "status", "reviewed_by", "reviewed_at", "review_comment", "updated_at",
    ])

    _log("DOC_REJECTED", rejected_by, document,
         f"Document '{document.label}' rejected.{f' Reason: {reason}' if reason else ''}")
    return document


# ── Sign + Publish ───────────────────────────────────────────────────────


@transaction.atomic
def sign_and_publish(
    *,
    document: DIDDocument,
    published_by: User,
    skip_review: bool = False,
) -> DIDDocument:
    """
    Sign via SignServer, publish via Universal Registrar.

    Allowed source statuses:
      - APPROVED (normal flow after review)
      - DRAFT    (ORG_ADMIN direct publish, set skip_review=True)
    """
    allowed = {DocumentStatus.APPROVED}
    if skip_review:
        allowed.add(DocumentStatus.DRAFT)

    if document.status not in allowed:
        if skip_review:
            raise ValidationError(
                f"Only DRAFT or APPROVED documents can be published. Status: {document.status}."
            )
        raise ValidationError(
            f"Only APPROVED documents can be published. Status: {document.status}."
        )

    # Validate VMs
    revoked = DocumentVerificationMethod.objects.filter(
        document=document, is_active=True, certificate__status="REVOKED"
    ).count()
    if revoked > 0:
        raise ValidationError(f"{revoked} verification method(s) reference revoked certificates.")

    active_vms = DocumentVerificationMethod.objects.filter(
        document=document, is_active=True
    ).count()
    if active_vms == 0:
        raise ValidationError("Add at least one verification method before publishing.")

    content = document.draft_content
    if not content:
        raise ValidationError("No draft content to publish.")

    # Step 1: Sign
    document.status = DocumentStatus.SIGNED
    document.save(update_fields=["status", "updated_at"])

    jws = _call_signserver(content)
    signed = add_proof_to_document(content, jws_signature=jws)

    _log("DOC_SIGNED", published_by, document, f"Document '{document.label}' signed.")

    # Step 2: Register
    is_first = document.current_version is None
    registrar_resp = _call_registrar(signed, is_create=is_first)

    # Step 3: Version
    next_ver = 1
    if document.current_version:
        next_ver = document.current_version.version_number + 1

    version = DIDDocumentVersion.objects.create(
        document=document,
        version_number=next_ver,
        content=signed,
        signature=jws,
        published_at=timezone.now(),
        published_by=published_by,
        registrar_response=registrar_resp,
    )

    # Step 4: Update document
    document.content = signed
    document.draft_content = None
    document.status = DocumentStatus.PUBLISHED
    document.current_version = version
    document.save(update_fields=[
        "content", "draft_content", "status", "current_version", "updated_at",
    ])

    _log("DOC_PUBLISHED", published_by, document,
         f"Document '{document.label}' published as v{next_ver}.",
         {"version": next_ver})

    logger.info("document_published", doc_id=str(document.id), version=next_ver)
    return document


# ── Deactivate ───────────────────────────────────────────────────────────


@transaction.atomic
def deactivate_document(
    *, document: DIDDocument, deactivated_by: User, reason: str = "",
) -> DIDDocument:
    if document.status != DocumentStatus.PUBLISHED:
        raise ValidationError(f"Only PUBLISHED documents can be deactivated.")

    did_uri = _did_uri_for(document)
    _call_registrar_deactivate(did_uri)

    document.status = DocumentStatus.DEACTIVATED
    document.save(update_fields=["status", "updated_at"])

    _log("DOC_DEACTIVATED", deactivated_by, document,
         f"Document '{document.label}' deactivated.{f' Reason: {reason}' if reason else ''}",
         {"reason": reason})
    return document


# ── VC builder ───────────────────────────────────────────────────────────


def get_verifiable_credential(document: DIDDocument) -> dict | None:
    """Build a VC for a published document. Returns None if not published."""
    if document.status != DocumentStatus.PUBLISHED or not document.content:
        return None

    did_uri = _did_uri_for(document)
    published_at = ""
    version = 0
    if document.current_version:
        published_at = (
            document.current_version.published_at.isoformat()
            if document.current_version.published_at
            else timezone.now().isoformat()
        )
        version = document.current_version.version_number

    owner_name = ""
    if document.owner:
        owner_name = getattr(document.owner, "full_name", "") or document.owner.email

    return build_verifiable_credential(
        did_uri=did_uri,
        did_document=document.content,
        org_name=document.organization.name,
        owner_name=owner_name,
        label=document.label,
        version=version,
        published_at=published_at,
    )


# ═════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═════════════════════════════════════════════════════════════════════════


def _require_editable(document):
    editable = {DocumentStatus.DRAFT, DocumentStatus.REJECTED, DocumentStatus.PUBLISHED}
    if document.status not in editable:
        raise ValidationError(f"Cannot edit a {document.status} document.")


def _validate_relationships(relationships):
    valid = {r.value for r in VerificationRelationship}
    for r in relationships:
        if r not in valid:
            raise ValidationError(f"Invalid relationship: '{r}'. Valid: {', '.join(sorted(valid))}")


def _create_verification_methods(*, document, organization, vm_specs, user):
    from src.apps.certificates.selectors import get_certificate_by_id

    seen = set()
    for spec in vm_specs:
        cert_id = spec.get("certificate_id")
        fragment = spec.get("method_id_fragment", "").strip()
        rels = spec.get("relationships", ["authentication", "assertionMethod"])
        mtype = spec.get("method_type", "JsonWebKey2020")

        if not cert_id:
            raise ValidationError("certificate_id is required.")
        if not fragment:
            raise ValidationError("method_id_fragment is required.")
        if fragment in seen:
            raise ValidationError(f"Duplicate fragment '#{fragment}'.")
        seen.add(fragment)

        cert = get_certificate_by_id(cert_id=cert_id)
        if cert is None or str(cert.organization_id) != str(organization.id):
            raise NotFoundError(f"Certificate '{cert_id}' not found in this organization.")
        if cert.status != "ACTIVE":
            raise ValidationError(f"Certificate '{cert.label}' is {cert.status}. Must be ACTIVE.")

        _validate_relationships(rels)

        DocumentVerificationMethod.objects.create(
            document=document,
            certificate=cert,
            method_id_fragment=fragment,
            method_type=mtype,
            relationships=",".join(rels),
        )


def _assemble_from_db(document, did_uri, service_endpoints=None):
    from src.apps.documents.selectors import get_active_verification_methods
    vms = list(get_active_verification_methods(document_id=document.id))
    return assemble_did_document(
        did_uri=did_uri, verification_methods=vms, service_endpoints=service_endpoints,
    )


def _reassemble_draft(document):
    did_uri = _did_uri_for(document)
    did_json = _assemble_from_db(document, did_uri)
    document.draft_content = did_json
    document.save(update_fields=["draft_content", "updated_at"])


# ── External service stubs ───────────────────────────────────────────────


def _call_signserver(did_document: dict) -> str:
    from django.conf import settings
    url = getattr(settings, "SIGNSERVER_URL", "")
    worker = getattr(settings, "SIGNSERVER_WORKER_NAME", "DIDDocumentSigner")

    if url and "signserver-node" not in url:
        try:
            import requests
            canonical = json.dumps(did_document, sort_keys=True, separators=(",", ":"))
            r = requests.post(url, data=canonical.encode(), headers={
                "Content-Type": "application/json",
                "X-SignServer-WorkerName": worker,
            }, timeout=30)
            r.raise_for_status()
            return r.text.strip()
        except Exception as e:
            logger.error("signserver_failed", error=str(e))
            raise ValidationError(f"SignServer failed: {e}")

    logger.warning("signserver_stub")
    return "eyJhbGciOiJFUzI1NiJ9..STUB_SIGNATURE"


def _call_registrar(did_document: dict, is_create: bool) -> dict:
    from django.conf import settings
    url = getattr(settings, "UNIVERSAL_REGISTRAR_URL", "")

    if url and "uni-registrar-web" not in url:
        try:
            import requests
            endpoint = f"{url}/1.0/{'create' if is_create else 'update'}"
            payload = ({"method": "web", "didDocument": did_document} if is_create
                       else {"did": did_document.get("id"), "didDocument": did_document})
            r = requests.post(endpoint, json=payload, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("registrar_failed", error=str(e))
            raise ValidationError(f"Registrar failed: {e}")

    logger.warning("registrar_stub")
    return {"didState": {"state": "finished", "did": did_document.get("id", "")}}


def _call_registrar_deactivate(did_uri: str) -> dict:
    from django.conf import settings
    url = getattr(settings, "UNIVERSAL_REGISTRAR_URL", "")

    if url and "uni-registrar-web" not in url:
        try:
            import requests
            r = requests.post(f"{url}/1.0/deactivate", json={"did": did_uri}, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("registrar_deactivate_failed", error=str(e))
            raise ValidationError(f"Deactivation failed: {e}")

    logger.warning("registrar_deactivate_stub")
    return {"didState": {"state": "finished", "did": did_uri}}


def _log(action, actor, document, description, metadata=None):
    try:
        from src.apps.audits.services import log_action
        log_action(
            actor=actor, action=action,
            resource_type="DID_DOCUMENT", resource_id=document.id,
            organization=document.organization,
            description=description, metadata=metadata or {},
        )
    except Exception as e:
        logger.warning("audit_log_failed", error=str(e))