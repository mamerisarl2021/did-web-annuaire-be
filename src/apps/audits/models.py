"""
Audit log model.

Immutable records of all significant platform actions.
Denormalized so logs survive entity deletion.
"""

import uuid

from django.db import models


class AuditAction(models.TextChoices):
    # Organization lifecycle
    ORG_CREATED = "ORG_CREATED", "Organization created"
    ORG_APPROVED = "ORG_APPROVED", "Organization approved"
    ORG_REJECTED = "ORG_REJECTED", "Organization rejected"
    ORG_SUSPENDED = "ORG_SUSPENDED", "Organization suspended"

    # Membership
    MEMBER_INVITED = "MEMBER_INVITED", "Member invited"
    MEMBER_ACTIVATED = "MEMBER_ACTIVATED", "Member activated"
    MEMBER_ROLE_CHANGED = "MEMBER_ROLE_CHANGED", "Member role changed"
    MEMBER_DEACTIVATED = "MEMBER_DEACTIVATED", "Member deactivated"

    # Certificates
    CERT_UPLOADED = "CERT_UPLOADED", "Certificate uploaded"
    CERT_ROTATED = "CERT_ROTATED", "Certificate rotated"
    CERT_REVOKED = "CERT_REVOKED", "Certificate revoked"

    # DID Documents
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

    # Auth
    USER_LOGIN = "USER_LOGIN", "User login"
    USER_PASSWORD_CHANGED = "USER_PASSWORD_CHANGED", "Password changed"
    USER_PASSWORD_RESET = "USER_PASSWORD_RESET", "Password reset"

    # Resolve (public)
    DID_RESOLVED = "DID_RESOLVED", "DID document resolved"
    DID_SEARCHED = "DID_SEARCHED", "DID search performed"


class ResourceType(models.TextChoices):
    ORGANIZATION = "ORGANIZATION", "Organization"
    MEMBERSHIP = "MEMBERSHIP", "Membership"
    CERTIFICATE = "CERTIFICATE", "Certificate"
    DID_DOCUMENT = "DID_DOCUMENT", "DID Document"
    USER = "USER", "User"


class AuditLog(models.Model):
    """
    Immutable audit log entry. No updated_at — once written, never modified.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ── Who ─────────────────────────────────────────────────────────
    actor = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    actor_email = models.CharField(
        max_length=255,
        help_text="Denormalized — survives user deletion.",
    )

    # ── Where ───────────────────────────────────────────────────────
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )

    # ── What ────────────────────────────────────────────────────────
    action = models.CharField(
        max_length=30,
        choices=AuditAction.choices,
    )
    resource_type = models.CharField(
        max_length=20,
        choices=ResourceType.choices,
    )
    resource_id = models.UUIDField(
        help_text="PK of the affected resource.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Human-readable summary.",
    )

    # ── Context ─────────────────────────────────────────────────────
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Extra context: old_status→new_status, fingerprint, etc.",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    # ── When ────────────────────────────────────────────────────────
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