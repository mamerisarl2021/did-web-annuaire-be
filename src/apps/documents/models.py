"""
Modèles de document DID.

Documents DID à l'échelle de l'organisation suivant la méthode did:web.
Modèle d'URI : did:web:<host>:<org_slug>:<user>:<label>
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
        help_text="Segment de chemin dans l'URI DID : did:web:<host>:<org_slug>:<user>:<label>",
    )

    owner = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="owned_documents",
        help_text="L'utilisateur qui a créé et possède ce document. "
        "Apparaît dans l'URI DID comme segment <user>. "
        "Seul cet utilisateur peut modifier le document.",
    )

    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.DRAFT,
    )

    content = models.JSONField(
        null=True,
        blank=True,
        help_text="Dernier JSON de document DID publié. Immuable une fois défini ; "
        "écrasé uniquement lors de la prochaine publication.",
    )
    draft_content = models.JSONField(
        null=True,
        blank=True,
        help_text="Brouillon de travail. Modifiable UNIQUEMENT par le propriétaire. "
        "Devient contenu lors de la publication.",
    )

    submitted_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_documents",
        help_text="Soumetteur du document",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    reviewed_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_documents",
        help_text="Administrateur de l'organisation qui a approuvé ou rejeté.",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(
        blank=True,
        default="",
        help_text="Commentaire d'approbation ou de rejet de l'administrateur de l'organisation.",
    )
    
    current_version = models.OneToOneField(
        "documents.DIDDocumentVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Pointe vers la version publiée la plus récente.",
    )

    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_documents",
        help_text="Identique au propriétaire à la création. Conservé pour la cohérence de BaseModel.",
    )

    class Meta:
        db_table = "did_documents"
        ordering = ["-created_at"]
        constraints = [
            # Un utilisateur ne peut avoir qu'un seul doc avec une étiquette donnée par org
            models.UniqueConstraint(
                fields=["organization", "owner", "label"],
                name="unique_doc_label_per_owner_per_org",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"did:web:...:{self.organization.slug}:{self.owner_identifier}:{self.label}"
        )

    @property
    def owner_identifier(self) -> str:
        """
        Le segment <user> pour l'URI DID.
        Utilise la partie locale de l'e-mail du propriétaire (avant @), slugifié.
        """
        if self.owner:
            local_part = self.owner.email.split("@")[0]
            # Remplace les points et les caractères spéciaux par des tirets pour la sécurité des URI
            import re

            return re.sub(r"[^a-zA-Z0-9-]", "-", local_part).strip("-").lower()
        return "unknown"

    @property
    def did_uri_suffix(self) -> str:
        """Retourne la partie org_slug:user:label. L'URI complet nécessite la conf de l'hôte."""
        return f"{self.organization.slug}:{self.owner_identifier}:{self.label}"

    def is_owner(self, user) -> bool:
        """Vérifie si l'utilisateur donné est le propriétaire de ce document."""
        return self.owner_id == user.id

    def can_edit(self, user) -> bool:
        """
        Seul le propriétaire peut modifier un doc, et uniquement dans les états modifiables.
        Les admins de l'organisation NE PEUVENT PAS modifier — ils peuvent seulement examiner.
        """
        if not self.is_owner(user):
            return False
        return self.status in (
            DocumentStatus.DRAFT,
            DocumentStatus.REJECTED,  # Le propriétaire peut réviser après rejet
        )

    def can_submit_for_review(self, user) -> bool:
        """Seul le proprio peut soumettre depuis DRAFT ou REJECTED, ou en mettant à jour PUBLISHED."""
        if not self.is_owner(user):
            return False
        return (
            self.status in (DocumentStatus.DRAFT, DocumentStatus.REJECTED)
            or self.has_pending_draft
        )

    def can_review(self, user) -> bool:
        """
        Seuls les administrateur de l'organisation peuvent examiner, et uniquement PENDING_REVIEW.
        Le propriétaire ne peut pas examiner son propre document.
        """
        if self.is_owner(user):
            return False
        return self.status == DocumentStatus.PENDING_REVIEW

    @property
    def has_pending_draft(self) -> bool:
        """
        True quand un document a été publié (le contenu existe) et a
        des modifications de brouillon non validées en attente d'examen ou de republication.
        """
        return (
            self.content is not None
            and self.draft_content is not None
            and self.draft_content != self.content
        )


class DIDDocumentVersion(BaseModel):
    document = models.ForeignKey(
        DIDDocument,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()

    content = models.JSONField(
        help_text="JSON complet du document DID au moment de la publication.",
    )

    signature = models.TextField(
        blank=True,
        default="",
        help_text="Bloc JWS ou de preuve depuis SignServer.",
    )

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
        help_text="Réponse depuis le Universal Registrar.",
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
    Lie un document DID à un certificat.
    Correspond à une entrée verificationMethod dans le JSON du document DID.
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
        help_text="Identifiant de fragment, par ex. 'key-1'. "
        "ID complet : did:web:...:org:user:label#key-1",
    )
    method_type = models.CharField(
        max_length=64,
        default="JsonWebKey2020",
        help_text="Type de méthode de vérification selon la spec DID.",
    )


    relationships = models.CharField(
        max_length=255,
        default="authentication,assertionMethod",
        help_text="Relations de vérification séparées par des virgules.",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Défini auto sur False quand le certificat lié est révoqué.",
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
