from django.contrib.auth.models import AbstractUser, PermissionsMixin
from django.db import models

from src.common.models import BaseModel

from .managers import UserManager


class ActivationMethod(models.TextChoices):
    OTP = "OTP", "OTP (Time-based)"
    QR = "QR", "QR Code"


class User(AbstractUser, PermissionsMixin, BaseModel):
    # ── Supprime les champs hérités de AbstractUser ─────────────────────────
    # Nous utilisons l'e-mail comme identifiant et full_name au lieu de first/last.
    username = None
    first_name = None
    last_name = None

    email = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=30, blank=True, default="")
    functions = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Titre du poste / rôle au sein de l'organisation.",
    )

    # État d'activation et d'authentification
    is_active = models.BooleanField(
        default=False,
        help_text="Devient True après l'activation OTP/QR. Contrôle la capacité de connexion.",
    )
    is_staff = models.BooleanField(default=False)
    is_superadmin = models.BooleanField(
        default=False,
        help_text="Administrateur au niveau de la plateforme. Distinct des rôles de l'organisation.",
    )

    # OTP / 2FA
    activation_method = models.CharField(
        max_length=20,
        choices=ActivationMethod.choices,
        default=ActivationMethod.OTP,
    )
    otp_secret = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Secret TOTP pour les applications d'authentification.",
    )
    account_activated_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "users"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        self.is_superuser = self.is_superadmin
        super().save(*args, **kwargs)
