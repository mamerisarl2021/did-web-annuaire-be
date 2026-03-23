"""
Modèles de certificat.

Un Certificat est l'identité stable — les méthodes de vérif DID y font référence.
CertificateVersion suit les téléchargements PEM réels, prenant en charge la rotation.
Lorsqu'un cert est tourné, une nouvelle CertificateVersion est créée et l'ancienne
est archivée. La révocation désactive ttes les méthodes de vérification liées.
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
        help_text="Nom convivial, par ex. 'prod-signature-2025'.",
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
        help_text="Pointe vers la version active de ce certificat.",
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
        help_text="Le fichier téléchargé.",
    )

    # ── JWK extrait (la sortie principale) ──────────────────────────
    public_key_jwk = models.JSONField(
        help_text="Représentation JWK extraite de la clé publique.",
    )

    # ── Métadonnées du certificat (extraites de X.509) ──────────────
    subject_dn = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="DN du sujet, par ex. 'CN=exemple,O=Acme'.",
    )
    issuer_dn = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="DN de l'émetteur, par ex. 'CN=EJBCA CA'.",
    )
    serial_number = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Numéro de série encodé en hexadécimal.",
    )
    not_valid_before = models.DateTimeField(
        null=True,
        blank=True,
    )
    not_valid_after = models.DateTimeField(
        null=True,
        blank=True,
    )

    # ── Infos sur la clé ────────────────────────────────────────────
    key_type = models.CharField(
        max_length=10,
        help_text="EC, RSA, ou Ed25519.",
    )
    key_curve = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="P-256, P-384, etc. Pour les clés EC.",
    )
    key_size = models.IntegerField(
        null=True,
        blank=True,
        help_text="2048, 4096, etc. Pour les clés RSA.",
    )

    # ── Empreinte digitale ──────────────────────────────────────────
    fingerprint_sha256 = models.CharField(
        max_length=64,
        help_text="Empreinte SHA-256 hexa du certificat encodé DER.",
    )

    is_current = models.BooleanField(
        default=True,
        help_text="Indicateur dénormalisé — True pour la version active.",
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
