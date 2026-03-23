"""
Modèle de journal d'audit.

Enregistrements immuables de toutes les actions importantes de la plateforme.
Dénormalisé pour survivre à la suppression d'entités.
"""

import uuid

from django.db import models


class AuditAction(models.TextChoices):
    # Cycle de vie de l'organisation
    ORG_CREATED = "ORG_CREATED", "Organization created"
    ORG_UPDATED = "ORG_UPDATED", "Organization updated"
    ORG_APPROVED = "ORG_APPROVED", "Organization approved"
    ORG_REJECTED = "ORG_REJECTED", "Organization rejected"
    ORG_SUSPENDED = "ORG_SUSPENDED", "Organization suspended"
    ORG_DELETED = "ORG_DELETED", "Organization deleted"

    # Adhésion
    MEMBER_INVITED = "MEMBER_INVITED", "Member invited"
    MEMBER_ACTIVATED = "MEMBER_ACTIVATED", "Member activated"
    MEMBER_ROLE_CHANGED = "MEMBER_ROLE_CHANGED", "Member role changed"
    MEMBER_DEACTIVATED = "MEMBER_DEACTIVATED", "Member deactivated"

    # Certificats
    CERT_UPLOADED = "CERT_UPLOADED", "Certificate uploaded"
    CERT_ROTATED = "CERT_ROTATED", "Certificate rotated"
    CERT_REVOKED = "CERT_REVOKED", "Certificate revoked"

    # Documents DID
    DOC_CREATED = "DOC_CREATED", "Document created"
    DOC_DRAFT_UPDATED = "DOC_DRAFT_UPDATED", "Document draft updated"
    DOC_VM_ADDED = "DOC_VM_ADDED", "Verification method added"
    DOC_VM_REMOVED = "DOC_VM_REMOVED", "Verification method removed"
    DOC_SUBMITTED = "DOC_SUBMITTED", "Document submitted for review"
    DOC_APPROVED = "DOC_APPROVED", "Document approved"
    DOC_REJECTED = "DOC_REJECTED", "Document rejected"
    DOC_SIGNED = "DOC_SIGNED", "Document signed"
    DOC_PUBLISHED = "DOC_PUBLISHED", "Document published"
    DOC_DEACTIVATED = "DOC_DEACTIVATED", "Document deactivated"

    # Authentification
    USER_LOGIN = "USER_LOGIN", "User login"
    USER_LOGOUT = "USER_LOGOUT", "User logout"
    USER_ACTIVATED = "USER_ACTIVATED", "User account activated"
    USER_UPDATED = "USER_UPDATED", "User account updated"
    USER_PASSWORD_CHANGED = "USER_PASSWORD_CHANGED", "Password changed"
    USER_PASSWORD_RESET = "USER_PASSWORD_RESET", "Password reset"

    # Résoudre (public)
    DID_RESOLVED = "DID_RESOLVED", "DID document resolved"
    DID_SEARCHED = "DID_SEARCHED", "DID search performed"


class ResourceType(models.TextChoices):
    ORGANIZATION = "ORGANIZATION", "Organization"
    MEMBERSHIP = "MEMBERSHIP", "Membership"
    CERTIFICATE = "CERTIFICATE", "Certificate"
    DID_DOCUMENT = "DID_DOCUMENT", "DID Document"
    USER = "USER", "User Account"


class AuditLog(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    actor = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    actor_email = models.CharField(
        max_length=255,
        help_text="Dénormalisé — survit à la suppression de l'utilisateur.",
    )

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )

    action = models.CharField(
        max_length=30,
        choices=AuditAction.choices,
    )
    resource_type = models.CharField(
        max_length=20,
        choices=ResourceType.choices,
    )
    resource_id = models.UUIDField(
        help_text="PK de la ressource concernée.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Résumé lisible par un humain.",
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Contexte sup : old_status→new_status, empreinte, etc.",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["resource_type", "resource_id"]),
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self) -> str:
        return f"[{self.action}] {self.resource_type}:{self.resource_id} by {self.actor_email}"
