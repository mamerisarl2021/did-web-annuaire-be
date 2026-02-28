"""
Certificate models.

A Certificate is the stable identity — DID verification methods reference it.
CertificateVersion tracks the actual PEM uploads, supporting rotation.
When a cert is rotated, a new CertificateVersion is created and the old one
is archived. Revocation deactivates all linked verification methods.
"""

from django.db import models

from src.common.models import BaseModel


class CertificateStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    REVOKED = "REVOKED", "Revoked"
    EXPIRED = "EXPIRED", "Expired"


class Certificate(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="certificates",
    )
    label = models.CharField(
        max_length=120,
        help_text="Human-friendly name, e.g. 'prod-signing-2025'.",
    )
    status = models.CharField(
        max_length=10,
        choices=CertificateStatus.choices,
        default=CertificateStatus.ACTIVE,
    )
    current_version = models.OneToOneField(
        "certificates.CertificateVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Points to the active version of this certificate.",
    )
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_certificates",
    )

    class Meta:
        db_table = "certificates"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "label"],
                name="unique_cert_label_per_org",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.organization.slug}/{self.label}"


class CertificateVersion(BaseModel):
    certificate = models.ForeignKey(
        Certificate,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    certificate_file = models.ForeignKey(
        "files.File",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="The uploaded PEM file.",
    )

    # ── Extracted JWK (the core output) ─────────────────────────────
    public_key_jwk = models.JSONField(
        help_text="Extracted JWK representation of the public key.",
    )

    # ── Certificate metadata (extracted from X.509) ─────────────────
    subject_dn = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Subject DN, e.g. 'CN=example,O=Acme'.",
    )
    issuer_dn = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Issuer DN, e.g. 'CN=EJBCA CA'.",
    )
    serial_number = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Hex-encoded serial number.",
    )
    not_valid_before = models.DateTimeField(
        null=True,
        blank=True,
    )
    not_valid_after = models.DateTimeField(
        null=True,
        blank=True,
    )

    # ── Key info ────────────────────────────────────────────────────
    key_type = models.CharField(
        max_length=10,
        help_text="EC, RSA, or Ed25519.",
    )
    key_curve = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="P-256, P-384, etc. EC keys only.",
    )
    key_size = models.IntegerField(
        null=True,
        blank=True,
        help_text="2048, 4096, etc. RSA keys only.",
    )

    # ── Fingerprint ─────────────────────────────────────────────────
    fingerprint_sha256 = models.CharField(
        max_length=64,
        help_text="Hex SHA-256 of the DER-encoded certificate.",
    )

    is_current = models.BooleanField(
        default=True,
        help_text="Denormalized flag — True for the active version.",
    )

    uploaded_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )

    class Meta:
        db_table = "certificate_versions"
        ordering = ["-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["certificate", "version_number"],
                name="unique_version_per_cert",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.certificate} v{self.version_number}"