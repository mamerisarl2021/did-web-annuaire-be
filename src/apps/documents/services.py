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
    sign_and_attach_proof,
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


# ── Mettre à jour le brouillon ──────────────────────────────────────────


@transaction.atomic
def update_draft(
        *,
        document: DIDDocument,
        updated_by: User,
        verification_methods: list[dict] | None = None,
        service_endpoints: list[dict] | None = None,
) -> DIDDocument:
    """
    Met à jour le contenu brouillon d'un document.

    Statuts autorisés : DRAFT, REJECTED, PUBLISHED.
      - DRAFT/REJECTED : édition normale avant (re-)soumission.
      - PUBLISHED : l'édition crée un nouveau brouillon pour la prochaine version.
        Le contenu en direct reste dans `content` ; les modifs vont dans `draft_content`.
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


# ── Signer + Publier (Modèle SAGA) ──────────────────────────────────────
#
# Étapes :
#   1. _validate_for_publish() — vérifications en lecture seule, aucune écriture
#   2. sign_and_attach_proof()  — pure crypto, pas d'état externe
#   3. _call_registrar()        — changement d'état externe (hors atomicité)
#   4. _persist_publish()       — écriture DB dans atomic()
#   5. Sur échec étape 4         — _call_registrar_deactivate() pour annuler l'étape 3
#
# Le statut intermédiaire SIGNED est supprimé. Nous passons directement du
# statut source à PUBLISHED dans une seule écriture DB atomique.
# L'entrée d'audit DOC_SIGNED est conservée pour enregistrer l'événement de signature.


def sign_and_publish(
        *,
        document: DIDDocument,
        published_by: User,
        skip_review: bool = False,
) -> DIDDocument:
    """
    Signer via SignServer (ecdsa-jcs-2019) et publier via Universal Registrar.

    Statuts sources autorisés :
      - APPROVED   : flux normal après examen
      - DRAFT      : publication directe ORG_ADMIN (skip_review=True)
      - PUBLISHED  : re-publier avec draft_content mis à jour (nouvelle version)

    Pour la republi. depuis PUBLISHED, draft_content doit différer de content.
    """
    # ── Étape 1 : Valider (pur — aucune écriture) ───────────────────
    _validate_for_publish(document, skip_review)

    content = document.draft_content
    if not content:
        raise ValidationError("No draft content to publish.")

    # ── Étape 2 : Signer (pure crypto — pas de changement d'état ext) ────────
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

    # ── Étape 3 : Enregistrer en externe (hors transaction) ─────────
    is_first = document.current_version is None
    registrar_resp = _call_registrar(signed_doc, is_create=is_first)

    # ── Étape 4 : Persister dans la BD de manière atomique ──────────
    # Sur échec → Étape 5 : désactivation compensatoire pr annuler l'étape 3.
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
    """Validation pure en lecture seule avant de signer/publier. Lève ValidationError."""
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
    Écriture BD atomique : créer l'enreg de version et promouvoir le brouillon en direct.
    Appelé après le succès externe de signature + enregistrement.
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

def issue_generic_credential(
        *,
        payload: dict,
        output_format: str,
) -> str | dict:
    """
    Issues a credential based on the requested output format.
    All signing is deferred to SignServer (ECDSA P-256).
    """
    from src.integrations.signserver import sign_bytes
    from src.common.did.assembler import _der_to_raw_ecdsa
    if output_format == "qr-cbor-base45":
        import cbor2
        import base45
        # 1. Convert claims to CBOR
        cbor_payload = cbor2.dumps(payload)
        # 2. Build COSE Sign1 Structure (Protected Header: Alg ES256)
        protected_header = cbor2.dumps({1: -7})
        unprotected_header = {}

        # To Be Signed (TBS) bytes
        sig_structure = ["Signature1", protected_header, b'', cbor_payload]
        tbs_bytes = cbor2.dumps(sig_structure)

        # 3. Hash and Sign via SignServer
        import hashlib
        hash_data = hashlib.sha256(tbs_bytes).digest()
        der_signature = sign_bytes(hash_data)
        raw_sig = _der_to_raw_ecdsa(der_signature, key_size=32)

        # 4. Final COSE Sign1 array
        cose_sign1 = [protected_header, unprotected_header, cbor_payload, raw_sig]
        cose_bytes = cbor2.dumps(cose_sign1)

        # 5. Compress & Encode
        compressed = zlib.compress(cose_bytes)
        b45_encoded = base45.b45encode(compressed).decode('utf-8')

        return f"CRED1:{b45_encoded}"
    elif output_format == "vc-jwt":
        # 1. Build JWT Header and Payload
        header = {"alg": "ES256", "typ": "JWT"}
        b64_header = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
        b64_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()

        # 2. Construct Signing Input
        signing_input = f"{b64_header}.{b64_payload}".encode()

        # 3. Hash and Sign via SignServer
        import hashlib
        hash_data = hashlib.sha256(signing_input).digest()
        der_signature = sign_bytes(hash_data)
        raw_sig = _der_to_raw_ecdsa(der_signature, key_size=32)

        # 4. Assemble standard JWT
        b64_sig = base64.urlsafe_b64encode(raw_sig).rstrip(b"=").decode()
        return f"{b64_header}.{b64_payload}.{b64_sig}"

    elif output_format == "json-ld":
        from src.common.did.assembler import create_proof, add_proof_to_document
        from django.conf import settings

        domain = getattr(settings, "PLATFORM_DOMAIN_WITHOUT_SCHEME", "localhost")

        # 1. Build standard W3C VC
        vc = {
            "@context": ["https://www.w3.org/2018/credentials/v1"],
            "type": payload.get("credential_type", ["VerifiableCredential"]),
            "issuer": f"did:web:{domain.replace(':', '%3A')}",
            "credentialSubject": {
                "id": payload.get("subject_id"),
                **payload.get("claims", {})
            }
        }

        # 2. Sign via existing ecdsa-jcs-2019 implementation
        proof = create_proof(vc, verification_method_id=f"did:web:{domain}#key-1")
        return add_proof_to_document(vc, proof)
    raise ValueError(f"Unsupported output format: {output_format}")

# ═════════════════════════════════════════════════════════════════════════
# Aides internes
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
