"""
Organization and Membership models.

Organizations go through PENDING_REVIEW → APPROVED (by superadmin) lifecycle.
Authorization document belongs on the Organization model because it's proof
about the organization itself, not the user.
"""

import uuid

from django.conf import settings
from django.db import models

from src.common.models import BaseModel
from src.common.types import MembershipStatus, OrgStatus, Role


class Organization(BaseModel):
    name = models.CharField(max_length=255)
    slug = models.SlugField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="URL-safe identifier. Used in DID URI path.",
    )
    description = models.TextField(blank=True, default="")
    type = models.CharField(blank=True, default="", max_length=50)
    country = models.CharField(max_length=100, blank=True, default="")
    address = models.TextField(blank=True, default="")
    email = models.EmailField(
        blank=True,
        default="",
        help_text="Official organization contact email.",
    )

    # ── Registration documents ──────────────────────────────────────────
    authorization_document = models.ForeignKey(
        "files.File",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="org_authorization_docs",
        help_text="Required. Administrative proof for platform registration.",
    )
    justification_document = models.ForeignKey(
        "files.File",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="org_justification_docs",
        help_text="Optional. Additional justification document.",
    )

    # ── Lifecycle ───────────────────────────────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in OrgStatus],
        default=OrgStatus.PENDING_REVIEW,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="founded_orgs",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_orgs",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "organizations"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"


class Membership(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=[(r.value, r.value) for r in Role],
        db_index=True,
    )
    status = models.CharField(
        max_length=25,
        choices=[(s.value, s.value) for s in MembershipStatus],
        default=MembershipStatus.INVITED,
        db_index=True,
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_invitations",
    )
    invitation_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
    )
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "memberships"
        unique_together = [("user", "organization")]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user.email} → {self.organization.slug} ({self.role})"