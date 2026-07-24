"""
Services de Document DID (opérations d'écriture).
"""

import re

import json
import base64
import zlib
import structlog
from django.db import transaction
from django.utils import timezone

from src.apps.certificates.models import CertificateStatus
from src.apps.documents.models import (
    DIDDocument,
    DIDDocumentVersion,
    DocumentStatus,
    DocumentVerificationMethod,
    VerificationRelationship,
)
from src.apps.users.models import User
from src.common.did.assembler import (
    assemble_did_document,
    build_did_uri,
    normalize_did_document,
    sign_and_attach_proof,
    write_did_json_to_disk,
)
from src.common.exceptions import ConflictError, NotFoundError, ValidationError

logger = structlog.get_logger(__name__)

LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,118}[a-z0-9]$")


def _did_uri_for(doc: DIDDocument) -> str:
    """Construit l'URI DID à partir des relations d'un document."""
    return build_did_uri(
        org_slug=doc.organization.slug,
        owner_identifier=doc.owner_identifier,
        label=doc.label,
    )


# ── Créer ───────────────────────────────────────────────────────────────


def _validate_controller(controller: str | list[str] | None) -> None:
    """
    Validate the controller field for a DID document.

    Rules per W3C DID Core spec:
      - None → self-controlled (valid, handled downstream)
      - str  → must be a valid DID URI (starts with "did:")
      - list → every item must be a valid DID URI, list must not be empty
    """
    if controller is None:
        return

    if isinstance(controller, str):
        if not controller.startswith("did:"):
            raise ValidationError(
                f"Controller must be a valid DID URI (starting with 'did:'). Got: '{controller}'"
            )
        return

    if isinstance(controller, list):
        if not controller:
            raise ValidationError("Controller list must not be empty.")
        for i, did in enumerate(controller):
            if not isinstance(did, str) or not did.startswith("did:"):
                raise ValidationError(
                    f"Controller[{i}] must be a valid DID URI (starting with 'did:'). Got: '{did}'"
                )
        return

    raise ValidationError("Controller must be a DID string, a list of DID strings, or null.")


@transaction.atomic
def create_document(
        *,
        organization,
        label: str,
        created_by: User,
        verification_methods: list[dict] | None = None,
        service_endpoints: list[dict] | None = None,
        controller: str | list[str] | None = None,
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

    _validate_controller(controller)

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
    did_json = _assemble_from_db(doc, did_uri, service_endpoints, controller=controller)
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


# ── Mettre à jour le brouillon ──────────────────────────────────────────


@transaction.atomic
def update_draft(
        *,
        document: DIDDocument,
        updated_by: User,
        verification_methods: list[dict] | None = None,
        service_endpoints: list[dict] | None = None,
        controller: str | list[str] | None = None,
) -> DIDDocument:
    """
    Met à jour le contenu brouillon d'un document.

    Statuts autorisés : DRAFT, REJECTED, PUBLISHED.
      - DRAFT/REJECTED : édition normale avant (re-)soumission.
      - PUBLISHED : l'édition crée un nouveau brouillon pour la prochaine version.
        Le contenu en direct reste dans `content` ; les modifs vont dans `draft_content`.
    """
    editable = {
        DocumentStatus.DRAFT,
        DocumentStatus.REJECTED,
        DocumentStatus.PUBLISHED,
        DocumentStatus.PUBLISH_FAILED,
    }
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

    _validate_controller(controller)

    did_uri = _did_uri_for(document)
    did_json = _assemble_from_db(document, did_uri, service_endpoints, controller=controller)
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


# ── Ajouter / supprimer méthodes de vérification ────────────────────────


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
        raise NotFoundError("Verification method not found.") from None

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


# ── Soumettre pour examen ───────────────────────────────────────────────


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

    from src.apps.organizations.selectors import invalidate_org_stats
    invalidate_org_stats(organization_id=document.organization_id, user_id=document.owner_id)

    logger.info("document_submitted", doc_id=str(document.id))
    return document


@transaction.atomic
def unsubmit_document(*, document: DIDDocument, unsubmitted_by: User) -> DIDDocument:
    if document.status != DocumentStatus.PENDING_REVIEW:
        raise ValidationError("Only PENDING_REVIEW documents can be unsubmitted.")

    document.status = DocumentStatus.DRAFT
    document.submitted_by = None
    document.submitted_at = None
    document.save(
        update_fields=["status", "submitted_by", "submitted_at", "updated_at"]
    )

    _log(
        "DOC_UNSUBMITTED",
        unsubmitted_by,
        document,
        f"Document '{document.label}' unsubmitted and returned to draft.",
    )

    logger.info("document_unsubmitted", doc_id=str(document.id))
    return document


@transaction.atomic
def remind_document_review(*, document: DIDDocument, reminded_by: User) -> DIDDocument:
    if document.status != DocumentStatus.PENDING_REVIEW:
        raise ValidationError("Only PENDING_REVIEW documents can be reminded.")
    # Rate limiting: 24 hours (86400 seconds)
    if document.last_reminded_at:
        time_since = timezone.now() - document.last_reminded_at
        if time_since.total_seconds() < 86400:
            raise ValidationError("Une relance a déjà été envoyée au cours des dernières 24 heures.")
    document.last_reminded_at = timezone.now()
    document.save(update_fields=["last_reminded_at", "updated_at"])
    # Trigger email
    from src.apps.emails.tasks import send_document_reminder_email

    display_name = reminded_by.get_full_name() or reminded_by.email
    send_document_reminder_email.delay(doc_id=document.id, user_name=display_name)
    _log(
        "DOC_REMINDER_SENT",
        reminded_by,
        document,
        f"Reminder sent for document '{document.label}'.",
    )
    logger.info("document_reminder_sent", doc_id=str(document.id))
    return document


# ── Approuver / rejeter ─────────────────────────────────────────────────


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

    from src.apps.organizations.selectors import invalidate_org_stats
    invalidate_org_stats(organization_id=document.organization_id, user_id=document.owner_id)

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

    from src.apps.organizations.selectors import invalidate_org_stats
    invalidate_org_stats(organization_id=document.organization_id, user_id=document.owner_id)

    logger.info("document_rejected", doc_id=str(document.id))
    return document


# ── Publication DID (DB d'abord, synchrone) ─────────────────────────────
#
#   1. _prepare_publish()     — transaction : version pendante + PUBLISHING
#   2. _publish_externally()  — Registrar + did.json (hors transaction)
#   3. _finalize_publish()    — transaction : promouvoir version → PUBLISHED
#   Sur échec externe         — _mark_publish_failed() : PUBLISH_FAILED


def sign_and_publish(
        *,
        document: DIDDocument,
        published_by: User,
        skip_review: bool = False,
) -> DIDDocument:
    """
    Publier un document DID via Universal Registrar.

    Statuts sources autorisés :
      - APPROVED, PUBLISH_FAILED : flux normal après examen
      - DRAFT : publication directe ORG_ADMIN (skip_review=True)
      - PUBLISHED : re-publier avec draft_content mis à jour
    """
    _validate_for_publish(document, skip_review)

    source_content = document.draft_content
    if (
        not source_content
        and document.status == DocumentStatus.PUBLISH_FAILED
        and document.pending_version_id
    ):
        source_content = document.pending_version.content

    content = normalize_did_document(source_content)
    if not content:
        raise ValidationError("No draft content to publish.")

    document, version = _prepare_publish(
        document=document,
        published_by=published_by,
        normalized_content=content,
    )

    did_uri = _did_uri_for(document)
    is_first = document.current_version is None

    try:
        registrar_resp = _publish_externally(content, is_create=is_first)
        write_did_json_to_disk(did_uri, content)
    except Exception as exc:
        _mark_publish_failed(document=document, error_message=str(exc))
        logger.error(
            "publish_external_failed",
            doc_id=str(document.id),
            error=str(exc),
        )
        raise ValidationError(f"Publication failed: {exc}") from exc

    return _finalize_publish(
        document=document,
        version=version,
        published_by=published_by,
        published_content=content,
        registrar_resp=registrar_resp,
    )


def _publish_externally(content: dict, *, is_create: bool) -> dict:
    return _call_registrar(content, is_create=is_create)


@transaction.atomic
def _prepare_publish(
        *,
        document: DIDDocument,
        published_by: User,
        normalized_content: dict,
) -> tuple[DIDDocument, DIDDocumentVersion]:
    if document.status == DocumentStatus.PUBLISHING:
        raise ValidationError("Publication already in progress.")

    if (
        document.status == DocumentStatus.PUBLISH_FAILED
        and document.pending_version_id
    ):
        version = document.pending_version
        version.content = normalized_content
        version.published_by = published_by
        version.save(update_fields=["content", "published_by", "updated_at"])
    else:
        if document.pending_version_id:
            document.pending_version.delete()

        next_ver = 1
        if document.current_version_id:
            next_ver = document.current_version.version_number + 1

        version = DIDDocumentVersion.objects.create(
            document=document,
            version_number=next_ver,
            content=normalized_content,
            signature="",
            published_by=published_by,
        )

    document.status = DocumentStatus.PUBLISHING
    document.pending_version = version
    document.publish_last_error = ""
    document.save(
        update_fields=[
            "status",
            "pending_version",
            "publish_last_error",
            "updated_at",
        ]
    )

    logger.info(
        "publish_prepared",
        doc_id=str(document.id),
        version=version.version_number,
    )
    return document, version


@transaction.atomic
def _finalize_publish(
        *,
        document: DIDDocument,
        version: DIDDocumentVersion,
        published_by: User,
        published_content: dict,
        registrar_resp: dict,
) -> DIDDocument:
    version.published_at = timezone.now()
    version.registrar_response = registrar_resp
    version.save(
        update_fields=["published_at", "registrar_response", "updated_at"]
    )

    document.content = published_content
    document.draft_content = None
    document.status = DocumentStatus.PUBLISHED
    document.current_version = version
    document.pending_version = None
    document.publish_last_error = ""
    document.save(
        update_fields=[
            "content",
            "draft_content",
            "status",
            "current_version",
            "pending_version",
            "publish_last_error",
            "updated_at",
        ]
    )

    _log(
        "DOC_PUBLISHED",
        published_by,
        document,
        f"Document '{document.label}' published as v{version.version_number}.",
        {
            "version": version.version_number,
            "is_update": version.version_number > 1,
        },
    )

    from src.apps.organizations.selectors import invalidate_org_stats
    invalidate_org_stats(
        organization_id=document.organization_id,
        user_id=document.owner_id,
    )

    logger.info(
        "document_published",
        doc_id=str(document.id),
        version=version.version_number,
        is_update=version.version_number > 1,
    )
    return document


@transaction.atomic
def _mark_publish_failed(*, document: DIDDocument, error_message: str) -> DIDDocument:
    document.status = DocumentStatus.PUBLISH_FAILED
    document.publish_last_error = error_message
    document.save(update_fields=["status", "publish_last_error", "updated_at"])

    from src.apps.organizations.selectors import invalidate_org_stats
    invalidate_org_stats(
        organization_id=document.organization_id,
        user_id=document.owner_id,
    )

    logger.warning(
        "publish_failed",
        doc_id=str(document.id),
        error=error_message,
    )
    return document


def _validate_for_publish(document: DIDDocument, skip_review: bool) -> None:
    """Validation pure en lecture seule avant publication."""
    if document.status == DocumentStatus.PUBLISHING:
        raise ValidationError("Publication already in progress.")

    allowed = {
        DocumentStatus.APPROVED,
        DocumentStatus.PUBLISHED,
        DocumentStatus.PUBLISH_FAILED,
    }
    if skip_review:
        allowed.add(DocumentStatus.DRAFT)

    if document.status not in allowed:
        if skip_review:
            raise ValidationError(
                f"Only DRAFT, APPROVED, PUBLISHED, or PUBLISH_FAILED documents "
                f"can be published. Status: {document.status}."
            )
        raise ValidationError(
            f"Only APPROVED, PUBLISHED, or PUBLISH_FAILED documents can be published. "
            f"Status: {document.status}."
        )

    if document.status == DocumentStatus.PUBLISH_FAILED:
        if not document.draft_content and not document.pending_version_id:
            raise ValidationError(
                "No draft content available to retry publication."
            )
    elif document.status == DocumentStatus.PUBLISHED:
        if not document.draft_content:
            raise ValidationError(
                "No pending changes to publish. Edit the document first."
            )
        if document.draft_content == document.content:
            raise ValidationError(
                "Draft content is identical to the published version. "
                "Make changes before re-publishing."
            )

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


# ── Désactiver ──────────────────────────────────────────────────────────


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
# Aides internes
# ═════════════════════════════════════════════════════════════════════════


def _require_editable(document):
    editable = {
        DocumentStatus.DRAFT,
        DocumentStatus.REJECTED,
        DocumentStatus.PUBLISHED,
        DocumentStatus.PUBLISH_FAILED,
    }
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


def _assemble_from_db(document, did_uri, service_endpoints=None, controller=None):
    from src.apps.documents.selectors import get_active_verification_methods

    vms = list(get_active_verification_methods(document_id=document.id))
    return assemble_did_document(
        did_uri=did_uri,
        verification_methods=vms,
        service_endpoints=service_endpoints,
        controller=controller,
    )


def _service_specs_from_draft(draft_content: dict | None) -> list[dict] | None:
    """Extract service endpoint specs from an assembled draft for reassembly."""
    if not draft_content:
        return None
    services = draft_content.get("service")
    if not services:
        return None

    specs = []
    for entry in services:
        if not isinstance(entry, dict):
            continue
        full_id = entry.get("id", "")
        fragment = full_id.rsplit("#", 1)[-1] if full_id else ""
        endpoint = entry.get("serviceEndpoint", entry.get("endpoint", ""))
        specs.append(
            {
                "id": fragment or entry.get("id", ""),
                "type": entry.get("type", "LinkedDomains"),
                "endpoint": endpoint,
            }
        )
    return specs or None


def _reassemble_draft(document):
    did_uri = _did_uri_for(document)

    # Conserve le contrôleur et les services lors du réassemblage du brouillon
    existing_controller = None
    service_endpoints = None
    if document.draft_content:
        if "controller" in document.draft_content:
            existing_controller = document.draft_content["controller"]
        service_endpoints = _service_specs_from_draft(document.draft_content)

    did_json = _assemble_from_db(
        document,
        did_uri,
        service_endpoints=service_endpoints,
        controller=existing_controller,
    )
    document.draft_content = did_json
    document.save(update_fields=["draft_content", "updated_at"])


# ── Clients de services externes ────────────────────────────────────────


def _call_registrar(did_document: dict, is_create: bool) -> dict:
    """
    Enregistrer ou mettre à jour un document DID via Universal Registrar.
    Appelé HORS DE @transaction.atomic — le résultat alimente _persist_publish.
    """
    from src.integrations.registrar import create_did, update_did

    if is_create:
        return create_did(did_document)
    else:
        return update_did(did_document)


def _call_registrar_deactivate(did_uri: str) -> dict:
    """
    Désactiver un DID via Universal Registrar.
    Utilisé par deactivate_document() et comme comp. dans la saga sign_and_publish.
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
