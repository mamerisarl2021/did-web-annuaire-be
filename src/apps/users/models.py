from django.contrib.auth.models import AbstractUser, PermissionsMixin
from django.db import models

from src.common.models import BaseModel

from .managers import UserManager


class ActivationMethod(models.TextChoices):
    OTP = "OTP", "OTP (Time-based)"
    QR = "QR", "QR Code"


class User(AbstractUser, PermissionsMixin, BaseModel):
    # ── Kill fields inherited from AbstractUser ─────────────────────
    # We use email as login and full_name instead of first/last.
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
        help_text="Job title / role within the organization.",
    )

    # Activation & auth state
    is_active = models.BooleanField(
        default=False,
        help_text="Becomes True after OTP/QR activation. Controls login ability.",
    )
    is_staff = models.BooleanField(default=False)
    is_superadmin = models.BooleanField(
        default=False,
        help_text="Platform-level admin. Separate from org roles.",
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
        help_text="TOTP secret for authenticator apps.",
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