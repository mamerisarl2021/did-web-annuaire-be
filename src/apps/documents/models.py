"""
DID Document models.

Organization-scoped DID documents following the did:web method.
URI pattern: did:web:<host>:<org_slug>:<user>:<label>

Ownership & permissions:
  - Any org member can CREATE a document (they become its owner).
  - Only the OWNER can EDIT their document (draft_content).
  - Even the org admin CANNOT edit a document they didn't create.
  - All org members can VIEW all documents in the organization.
  - The org admin REVIEWS and APPROVES/REJECTS documents submitted by members.

Lifecycle:
  DRAFT → PENDING_REVIEW → APPROVED → SIGNED → PUBLISHED → DEACTIVATED
                         ↘ REJECTED (→ back to DRAFT for edits by owner)
"""

from django.db import models

from src.common.models import BaseModel


class DocumentStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING_REVIEW = "PENDING_REVIEW", "Pending Review"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    SIGNED = "SIGNED", "Signed"
    PUBLISHED = "PUBLISHED", "Published"
    DEACTIVATED = "DEACTIVATED", "Deactivated"


class VerificationRelationship(models.TextChoices):
    AUTHENTICATION = "authentication", "Authentication"
    ASSERTION_METHOD = "assertionMethod", "Assertion Method"
    KEY_AGREEMENT = "keyAgreement", "Key Agreement"
    CAPABILITY_INVOCATION = "capabilityInvocation", "Capability Invocation"
    CAPABILITY_DELEGATION = "capabilityDelegation", "Capability Delegation"


class DIDDocument(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="did_documents",
    )
    label = models.CharField(
        max_length=120,
        help_text="Path segment in the DID URI: did:web:<host>:<org_slug>:<user>:<label>",
    )

    # ── Owner — the user who created this document ──────────────────
    # This user appears in the DID URI and is the ONLY person who can
    # edit draft_content. Org admins review but do NOT have write access.
    owner = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="owned_documents",
        help_text="The user who created and owns this document. "
                  "Appears in the DID URI as the <user> segment. "
                  "Only this user can edit the document.",
    )

    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.DRAFT,
    )

    # ── Content ─────────────────────────────────────────────────────
    content = models.JSONField(
        null=True,
        blank=True,
        help_text="Last published DID document JSON. Immutable once set; "
                  "overwritten only on next publish.",
    )
    draft_content = models.JSONField(
        null=True,
        blank=True,
        help_text="Working draft. Editable ONLY by the owner. "
                  "Becomes content on publish.",
    )

    # ── Review workflow ─────────────────────────────────────────────
    submitted_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_documents",
        help_text="The owner who submitted this document for review.",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    reviewed_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_documents",
        help_text="Org admin who approved or rejected.",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(
        blank=True,
        default="",
        help_text="Approval or rejection comment from the org admin.",
    )

    # ── Version tracking ────────────────────────────────────────────
    current_version = models.OneToOneField(
        "documents.DIDDocumentVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Points to the most recent published version.",
    )

    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_documents",
        help_text="Same as owner at creation time. Kept for BaseModel consistency.",
    )

    class Meta:
        db_table = "did_documents"
        ordering = ["-created_at"]
        constraints = [
            # A user can only have one document with a given label per org
            models.UniqueConstraint(
                fields=["organization", "owner", "label"],
                name="unique_doc_label_per_owner_per_org",
            ),
        ]

    def __str__(self) -> str:
        return f"did:web:...:{self.organization.slug}:{self.owner_identifier}:{self.label}"

    @property
    def owner_identifier(self) -> str:
        """
        The <user> segment for the DID URI.
        Uses the owner's email local part (before @), slugified.
        """
        if self.owner:
            local_part = self.owner.email.split("@")[0]
            # Replace dots and special chars with hyphens for URI safety
            import re
            return re.sub(r'[^a-zA-Z0-9-]', '-', local_part).strip('-').lower()
        return "unknown"

    @property
    def did_uri_suffix(self) -> str:
        """Returns the org_slug:user:label part. Full URI requires host config."""
        return f"{self.organization.slug}:{self.owner_identifier}:{self.label}"

    def is_owner(self, user) -> bool:
        """Check if the given user is the owner of this document."""
        return self.owner_id == user.id

    def can_edit(self, user) -> bool:
        """
        Only the owner can edit a document, and only in editable states.
        Org admins CANNOT edit — they can only review.
        """
        if not self.is_owner(user):
            return False
        return self.status in (
            DocumentStatus.DRAFT,
            DocumentStatus.REJECTED,  # Owner can revise after rejection
        )

    def can_submit_for_review(self, user) -> bool:
        """Only the owner can submit, and only from DRAFT or REJECTED status."""
        if not self.is_owner(user):
            return False
        return self.status in (DocumentStatus.DRAFT, DocumentStatus.REJECTED)

    def can_review(self, user) -> bool:
        """
        Only org admins can review, and only PENDING_REVIEW documents.
        The owner cannot review their own document.
        """
        if self.is_owner(user):
            return False
        return self.status == DocumentStatus.PENDING_REVIEW


class DIDDocumentVersion(BaseModel):
    document = models.ForeignKey(
        DIDDocument,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()

    # ── Snapshot ────────────────────────────────────────────────────
    content = models.JSONField(
        help_text="Full DID document JSON at the time of publish.",
    )

    # ── Signing ─────────────────────────────────────────────────────
    signature = models.TextField(
        blank=True,
        default="",
        help_text="JWS or proof block from SignServer.",
    )

    # ── Publishing ──────────────────────────────────────────────────
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )
    registrar_response = models.JSONField(
        null=True,
        blank=True,
        help_text="Response from the Universal Registrar.",
    )

    class Meta:
        db_table = "did_document_versions"
        ordering = ["-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "version_number"],
                name="unique_version_per_document",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document} v{self.version_number}"


class DocumentVerificationMethod(BaseModel):
    """
    Links a DID document to a certificate.
    Maps to a verificationMethod entry in the DID document JSON.

    A single document can have multiple verification methods (different certs).
    A single cert can appear in multiple documents.
    """

    document = models.ForeignKey(
        DIDDocument,
        on_delete=models.CASCADE,
        related_name="verification_methods",
    )
    certificate = models.ForeignKey(
        "certificates.Certificate",
        on_delete=models.CASCADE,
        related_name="verification_methods",
    )

    method_id_fragment = models.CharField(
        max_length=64,
        help_text="Fragment identifier, e.g. 'key-1'. "
                  "Full ID: did:web:...:org:user:label#key-1",
    )
    method_type = models.CharField(
        max_length=64,
        default="JsonWebKey2020",
        help_text="Verification method type per DID spec.",
    )

    # ── Relationships ───────────────────────────────────────────────
    # Stored as comma-separated values.
    # Choices: authentication, assertionMethod, keyAgreement,
    #          capabilityInvocation, capabilityDelegation
    relationships = models.CharField(
        max_length=255,
        default="authentication,assertionMethod",
        help_text="Comma-separated verification relationships.",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Auto-set to False when the linked certificate is revoked.",
    )

    class Meta:
        db_table = "document_verification_methods"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "method_id_fragment"],
                name="unique_method_fragment_per_doc",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document}#{self.method_id_fragment}"

    @property
    def relationship_list(self) -> list[str]:
        return [r.strip() for r in self.relationships.split(",") if r.strip()]