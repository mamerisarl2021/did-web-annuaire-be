"""
Modèles Organization et Membership.

Les organisations traversent le cycle de vie PENDING_REVIEW → APPROVED (par le superadmin).
Le document d'autorisation appartient au modèle Organization car c'est une preuve
concernant l'organisation elle-même, pas l'utilisateur.
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
        help_text="Identifiant sécurisé pour les URL. Utilisé dans le chemin de l'URI DID.",
    )
    description = models.TextField(blank=True, default="")
    type = models.CharField(blank=True, default="", max_length=50)
    country = models.CharField(max_length=100, blank=True, default="")
    address = models.TextField(blank=True, default="")
    email = models.EmailField(
        blank=True,
        default="",
        help_text="E-mail de contact officiel de l'organisation.",
    )

    # ── Documents d'inscription ─────────────────────────────────────────
    authorization_document = models.ForeignKey(
        "files.File",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="org_authorization_docs",
        help_text="Requis. Preuve administrative pour l'inscription sur la plateforme.",
    )
    justification_document = models.ForeignKey(
        "files.File",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="org_justification_docs",
        help_text="Optionnel. Document de justification supplémentaire.",
    )

    # ── Cycle de vie ────────────────────────────────────────────────────
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
    has_audit_access = models.BooleanField(
        default=False,
        help_text="Accorde à ce membre l'accès aux journaux d'audit. "
        "ORG_ADMIN a toujours un accès d'audit indépendamment de cet indicateur.",
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

    @property
    def can_view_audits(self) -> bool:
        """ORG_ADMIN peut toujours ; les autres ont besoin de l'indicateur."""
        return self.role == Role.ORG_ADMIN or self.has_audit_access
