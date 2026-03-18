"""
DID Document services (write operations).

Lifecycle:
  ORG_MEMBER: DRAFT → PENDING_REVIEW → APPROVED → PUBLISHED → DEACTIVATED
                                      → REJECTED → re-edit → DRAFT
  ORG_ADMIN:  DRAFT → PUBLISHED (direct, skips review)

Updates to PUBLISHED documents:
  Any owner or admin can edit draft_content on a PUBLISHED document.
  Re-publishing creates a new version. The document was already reviewed
  and approved once; subsequent edits go through a lighter flow:
    - ORG_ADMIN: edit → re-publish directly (new version)
    - ORG_MEMBER owner: edit → re-publish (new version)
  If stricter review is needed, the admin can deactivate the document.

sign_and_publish uses a SAGA pattern for all-or-none semantics with external services:
  1. Validate state (pure)
  2. Sign via SignServer (pure cryptographic computation — no external state change)
  3. Register via Universal Registrar (external state change)
  4. Persist to DB atomically
  5. On DB failure → compensating call: deactivate the DID from the registrar
"""

import re

import structlog
from django.db import transaction
from django.utils import timezone

from src.apps.certificates.models import CertificateStatus
from src.common.did.assembler import (
    assemble_did_document,
    build_did_uri,
    sign_and_attach_proof,
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
        organization_id=organization.id,
        owner_id=created_by.id,
        label=label,
    ):
        raise ConflictError(
            f"Label '{label}' already exists for you in this organization."
        )

    doc = DIDDocument.objects.create(
        organization=organization,
        label=label,
        status=DocumentStatus.DRAFT,
        owner=created_by,
        created_by=created_by,
    )

    if verification_methods:
        _create_verification_methods(
            document=doc,
            organization=organization,
            vm_specs=verification_methods,
            user=created_by,
        )

    did_uri = _did_uri_for(doc)
    did_json = _assemble_from_db(doc, did_uri, service_endpoints)
    doc.draft_content = did_json
    doc.save(update_fields=["draft_content", "updated_at"])

    _log(
        "DOC_CREATED",
        created_by,
        doc,
        f"DID document '{label}' created. URI: {did_uri}",
    )

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
    """
    Update the draft content of a document.

    Allowed statuses: DRAFT, REJECTED, PUBLISHED.
      - DRAFT/REJECTED: normal editing before (re-)submission.
      - PUBLISHED: editing creates a new draft for the next version.
        The live content stays in `content`; changes go into `draft_content`.
    """
    editable = {DocumentStatus.DRAFT, DocumentStatus.REJECTED, DocumentStatus.PUBLISHED}
    if document.status not in editable:
        raise ValidationError(f"Cannot edit a {document.status} document.")

    update_fields = ["draft_content", "updated_at"]
    was_rejected = document.status == DocumentStatus.REJECTED

    if was_rejected:
        # Reset review state so the owner can re-submit
        document.status = DocumentStatus.DRAFT
        document.reviewed_by = None
        document.reviewed_at = None
        document.review_comment = ""
        update_fields += ["status", "reviewed_by", "reviewed_at", "review_comment"]

    if verification_methods is not None:
        DocumentVerificationMethod.objects.filter(document=document).delete()
        _create_verification_methods(
            document=document,
            organization=document.organization,
            vm_specs=verification_methods,
            user=updated_by,
        )

    did_uri = _did_uri_for(document)
    did_json = _assemble_from_db(document, did_uri, service_endpoints)
    document.draft_content = did_json

    document.save(update_fields=update_fields)

    is_update = document.content is not None
    _log(
        "DOC_DRAFT_UPDATED",
        updated_by,
        document,
        f"Draft {'updated' if is_update else 'edited'} for '{document.label}'.",
        {"is_version_update": is_update},
    )

    logger.info("document_draft_updated", doc_id=str(document.id))
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
    if cert.status != CertificateStatus.ACTIVE:
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

    _log(
        "DOC_VM_ADDED",
        added_by,
        document,
        f"Verification method '#{method_id_fragment}' added to '{document.label}'.",
        {"fragment": method_id_fragment, "certificate_id": str(certificate_id)},
    )

    logger.info(
        "verification_method_added",
        doc_id=str(document.id),
        fragment=method_id_fragment,
    )
    return vm


@transaction.atomic
def remove_verification_method(*, document: DIDDocument, vm_id, removed_by: User):
    _require_editable(document)
    try:
        vm = DocumentVerificationMethod.objects.get(id=vm_id, document=document)
    except DocumentVerificationMethod.DoesNotExist:
        raise NotFoundError("Verification method not found.")

    fragment = vm.method_id_fragment
    vm.delete()
    _reassemble_draft(document)

    _log(
        "DOC_VM_REMOVED",
        removed_by,
        document,
        f"Verification method '#{fragment}' removed from '{document.label}'.",
        {"fragment": fragment},
    )

    logger.info(
        "verification_method_removed",
        doc_id=str(document.id),
        fragment=fragment,
    )


# ── Submit for review ────────────────────────────────────────────────────


@transaction.atomic
def submit_for_review(*, document: DIDDocument, submitted_by: User) -> DIDDocument:
    allowed = {DocumentStatus.DRAFT, DocumentStatus.REJECTED, DocumentStatus.PUBLISHED}
    if document.status not in allowed:
        raise ValidationError(
            f"Only editable documents can be submitted. Status: {document.status}."
        )

    if document.status == DocumentStatus.PUBLISHED and not document.has_pending_draft:
        raise ValidationError("No pending changes to submit.")

    active_vms = DocumentVerificationMethod.objects.filter(
        document=document, is_active=True
    ).count()
    if active_vms == 0:
        raise ValidationError("Add at least one verification method before submitting.")

    document.status = DocumentStatus.PENDING_REVIEW
    document.submitted_by = submitted_by
    document.submitted_at = timezone.now()
    document.save(
        update_fields=["status", "submitted_by", "submitted_at", "updated_at"]
    )

    from src.apps.emails.tasks import send_document_submitted_email

    send_document_submitted_email.delay(
        doc_id=str(document.id),
        org_id=str(document.organization_id),
        submitter_id=str(submitted_by.id),
    )

    _log(
        "DOC_SUBMITTED",
        submitted_by,
        document,
        f"Document '{document.label}' submitted for review.",
    )

    logger.info("document_submitted", doc_id=str(document.id))
    return document


# ── Approve / reject ────────────────────────────────────────────────────


@transaction.atomic
def approve_document(
    *,
    document: DIDDocument,
    approved_by: User,
    comment: str = "",
) -> DIDDocument:
    if document.status != DocumentStatus.PENDING_REVIEW:
        raise ValidationError("Only PENDING_REVIEW documents can be approved.")

    document.status = DocumentStatus.APPROVED
    document.reviewed_by = approved_by
    document.reviewed_at = timezone.now()
    document.review_comment = comment
    document.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_comment",
            "updated_at",
        ]
    )

    from src.apps.emails.tasks import send_document_reviewed_email

    send_document_reviewed_email.delay(
        doc_id=str(document.id),
        org_id=str(document.organization_id),
        reviewer_id=str(approved_by.id),
        action="approved",
        reason=comment,
    )

    _log(
        "DOC_APPROVED",
        approved_by,
        document,
        f"Document '{document.label}' approved.{f' Comment: {comment}' if comment else ''}",
    )

    logger.info("document_approved", doc_id=str(document.id))
    return document


@transaction.atomic
def reject_document(
    *,
    document: DIDDocument,
    rejected_by: User,
    reason: str = "",
) -> DIDDocument:
    if document.status != DocumentStatus.PENDING_REVIEW:
        raise ValidationError("Only PENDING_REVIEW documents can be rejected.")

    document.status = DocumentStatus.REJECTED
    document.reviewed_by = rejected_by
    document.reviewed_at = timezone.now()
    document.review_comment = reason
    document.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_comment",
            "updated_at",
        ]
    )

    from src.apps.emails.tasks import send_document_reviewed_email

    send_document_reviewed_email.delay(
        doc_id=str(document.id),
        org_id=str(document.organization_id),
        reviewer_id=str(rejected_by.id),
        action="rejected",
        reason=reason,
    )

    _log(
        "DOC_REJECTED",
        rejected_by,
        document,
        f"Document '{document.label}' rejected.{f' Reason: {reason}' if reason else ''}",
    )

    logger.info("document_rejected", doc_id=str(document.id))
    return document


# ── Sign + Publish (SAGA pattern) ───────────────────────────────────────
#
# Steps:
#   1. _validate_for_publish() — read-only checks, no writes
#   2. sign_and_attach_proof()  — pure crypto, no external state
#   3. _call_registrar()        — external state change (outside atomic)
#   4. _persist_publish()       — DB write inside atomic()
#   5. On step 4 failure        — _call_registrar_deactivate() to undo step 3
#
# The SIGNED intermediate status is removed. We go directly from the
# source status to PUBLISHED in a single atomic DB write.
# DOC_SIGNED audit entry is kept to record the signing event.


def sign_and_publish(
    *,
    document: DIDDocument,
    published_by: User,
    skip_review: bool = False,
) -> DIDDocument:
    """
    Sign via SignServer (ecdsa-jcs-2019) and publish via Universal Registrar.

    Allowed source statuses:
      - APPROVED   : normal flow after review
      - DRAFT      : ORG_ADMIN direct publish (skip_review=True)
      - PUBLISHED  : re-publish with updated draft_content (new version)

    For PUBLISHED re-publish, draft_content must differ from content.
    """
    # ── Step 1: Validate (pure — no writes) ─────────────────────────
    _validate_for_publish(document, skip_review)

    content = document.draft_content
    if not content:
        raise ValidationError("No draft content to publish.")

    # ── Step 2: Sign (pure crypto — no external state change) ────────
    signed_doc, proof_value = sign_and_attach_proof(content)

    _log(
        "DOC_SIGNED",
        published_by,
        document,
        f"Document '{document.label}' signed (ecdsa-jcs-2019).",
        {"cryptosuite": "ecdsa-jcs-2019"},
    )

    logger.info(
        "document_signed",
        doc_id=str(document.id),
        cryptosuite="ecdsa-jcs-2019",
    )

    # ── Step 3: Register externally (outside transaction) ────────────
    is_first = document.current_version is None
    registrar_resp = _call_registrar(signed_doc, is_create=is_first)

    # ── Step 4: Persist to DB atomically ─────────────────────────────
    # On failure → Step 5: compensating deactivate to undo step 3.
    did_uri = _did_uri_for(document)
    try:
        document = _persist_publish(
            document=document,
            published_by=published_by,
            signed_doc=signed_doc,
            proof_value=proof_value,
            registrar_resp=registrar_resp,
        )
    except Exception as db_error:
        logger.error(
            "publish_db_failed_compensating",
            doc_id=str(document.id),
            error=str(db_error),
        )
        try:
            _call_registrar_deactivate(did_uri)
            logger.warning(
                "registrar_compensated",
                doc_id=str(document.id),
                did_uri=did_uri,
            )
        except Exception as comp_error:
            # Compensation also failed — log prominently, requires manual intervention
            logger.critical(
                "registrar_compensation_failed",
                doc_id=str(document.id),
                did_uri=did_uri,
                db_error=str(db_error),
                comp_error=str(comp_error),
            )
        raise

    return document


def _validate_for_publish(document: DIDDocument, skip_review: bool) -> None:
    """Pure read-only validation before signing/publishing. Raises ValidationError."""
    allowed = {DocumentStatus.APPROVED, DocumentStatus.PUBLISHED}
    if skip_review:
        allowed.add(DocumentStatus.DRAFT)

    if document.status not in allowed:
        if skip_review:
            raise ValidationError(
                f"Only DRAFT, APPROVED, or PUBLISHED documents can be published. "
                f"Status: {document.status}."
            )
        raise ValidationError(
            f"Only APPROVED or PUBLISHED documents can be published. "
            f"Status: {document.status}."
        )

    # For re-publish, require draft_content exists and differs from live content
    if document.status == DocumentStatus.PUBLISHED:
        if not document.draft_content:
            raise ValidationError(
                "No pending changes to publish. Edit the document first."
            )
        if document.draft_content == document.content:
            raise ValidationError(
                "Draft content is identical to the published version. "
                "Make changes before re-publishing."
            )

    # Validate VMs — no revoked certificates
    revoked = DocumentVerificationMethod.objects.filter(
        document=document, is_active=True, certificate__status=CertificateStatus.REVOKED
    ).count()
    if revoked > 0:
        raise ValidationError(
            f"{revoked} verification method(s) reference revoked certificates."
        )

    active_vms = DocumentVerificationMethod.objects.filter(
        document=document, is_active=True
    ).count()
    if active_vms == 0:
        raise ValidationError("Add at least one verification method before publishing.")


@transaction.atomic
def _persist_publish(
    *,
    document: DIDDocument,
    published_by: User,
    signed_doc: dict,
    proof_value: str,
    registrar_resp: dict,
) -> DIDDocument:
    """
    Atomic DB write: create version record and promote draft → live.
    Called after external signing + registration succeed.
    """
    next_ver = 1
    if document.current_version:
        next_ver = document.current_version.version_number + 1

    version = DIDDocumentVersion.objects.create(
        document=document,
        version_number=next_ver,
        content=signed_doc,
        signature=proof_value,
        published_at=timezone.now(),
        published_by=published_by,
        registrar_response=registrar_resp,
    )

    document.content = signed_doc
    document.draft_content = None
    document.status = DocumentStatus.PUBLISHED
    document.current_version = version
    document.save(
        update_fields=[
            "content",
            "draft_content",
            "status",
            "current_version",
            "updated_at",
        ]
    )

    _log(
        "DOC_PUBLISHED",
        published_by,
        document,
        f"Document '{document.label}' published as v{next_ver}.",
        {
            "version": next_ver,
            "is_update": next_ver > 1,
            "cryptosuite": "ecdsa-jcs-2019",
        },
    )

    logger.info(
        "document_published",
        doc_id=str(document.id),
        version=next_ver,
        is_update=next_ver > 1,
    )
    return document


# ── Deactivate ───────────────────────────────────────────────────────────


@transaction.atomic
def deactivate_document(
    *,
    document: DIDDocument,
    deactivated_by: User,
    reason: str = "",
) -> DIDDocument:
    if not document.content or document.status == DocumentStatus.DEACTIVATED:
        raise ValidationError("Only active published documents can be deactivated.")

    did_uri = _did_uri_for(document)
    _call_registrar_deactivate(did_uri)

    document.status = DocumentStatus.DEACTIVATED
    document.save(update_fields=["status", "updated_at"])

    _log(
        "DOC_DEACTIVATED",
        deactivated_by,
        document,
        f"Document '{document.label}' deactivated.{f' Reason: {reason}' if reason else ''}",
        {"reason": reason},
    )

    logger.info("document_deactivated", doc_id=str(document.id))
    return document


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
            raise ValidationError(
                f"Invalid relationship: '{r}'. Valid: {', '.join(sorted(valid))}"
            )


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
            raise NotFoundError(
                f"Certificate '{cert_id}' not found in this organization."
            )
        if cert.status != CertificateStatus.ACTIVE:
            raise ValidationError(
                f"Certificate '{cert.label}' is {cert.status}. Must be ACTIVE."
            )

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
        did_uri=did_uri,
        verification_methods=vms,
        service_endpoints=service_endpoints,
    )


def _reassemble_draft(document):
    did_uri = _did_uri_for(document)
    did_json = _assemble_from_db(document, did_uri)
    document.draft_content = did_json
    document.save(update_fields=["draft_content", "updated_at"])


# ── External service clients ─────────────────────────────────────────────


def _call_registrar(did_document: dict, is_create: bool) -> dict:
    """
    Register or update a DID document via the Universal Registrar.
    Called OUTSIDE @transaction.atomic — result feeds into _persist_publish.
    """
    from src.integrations.registrar import create_did, update_did

    if is_create:
        return create_did(did_document)
    else:
        return update_did(did_document)


def _call_registrar_deactivate(did_uri: str) -> dict:
    """
    Deactivate a DID via the Universal Registrar.
    Used both by deactivate_document() and as compensation in sign_and_publish saga.
    """
    from src.integrations.registrar import deactivate_did

    return deactivate_did(did_uri)


def _log(action, actor, document, description, metadata=None):
    try:
        from src.apps.audits.services import log_action

        log_action(
            actor=actor,
            action=action,
            resource_type="DID_DOCUMENT",
            resource_id=document.id,
            organization=document.organization,
            description=description,
            metadata=metadata or {},
        )
    except Exception as e:
        logger.warning("audit_log_failed", error=str(e))
