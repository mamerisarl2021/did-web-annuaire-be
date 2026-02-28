"""
Authentication schemas.

Registration is multipart (Form fields + file uploads), so we don't use a
request Schema for it — the API endpoint uses Form() and File() parameters directly.
"""

from uuid import UUID

from ninja import Schema
from ninja_jwt.schema import TokenObtainPairInputSchema
from ninja_jwt.tokens import RefreshToken

from src.apps.users.models import User


# ── Custom token obtain (login) ─────────────────────────────────────────


class CustomTokenObtainPairInput(TokenObtainPairInputSchema):
    @classmethod
    def get_token(cls, user: User) -> RefreshToken:
        token = super().get_token(user)
        token["email"] = user.email
        token["full_name"] = user.full_name
        token["is_superadmin"] = user.is_superadmin
        return token


# ── Request schemas ─────────────────────────────────────────────────────


class ActivateVerifyRequestSchema(Schema):
    otp_code: str


class LogoutRequestSchema(Schema):
    refresh: str


class PasswordResetRequestSchema(Schema):
    email: str


class PasswordResetConfirmSchema(Schema):
    token: str
    new_password: str


class PasswordChangeSchema(Schema):
    old_password: str
    new_password: str


# ── Response schemas ────────────────────────────────────────────────────


class UserResponseSchema(Schema):
    id: UUID
    email: str
    full_name: str
    phone: str
    functions: str
    is_active: bool
    is_superadmin: bool
    activation_method: str
    account_activated_at: str | None = None
    created_at: str

    @staticmethod
    def resolve_account_activated_at(obj) -> str | None:
        return obj.account_activated_at.isoformat() if obj.account_activated_at else None

    @staticmethod
    def resolve_created_at(obj) -> str:
        return obj.created_at.isoformat()


class RegisterResponseSchema(Schema):
    message: str
    user: UserResponseSchema


class ActivateSetupResponseSchema(Schema):
    otp_uri: str
    qr_base64: str
    message: str


class ActivateVerifyResponseSchema(Schema):
    message: str
    access: str
    refresh: str
    user: UserResponseSchema


class LogoutResponseSchema(Schema):
    message: str


class MessageResponseSchema(Schema):
    message: str


class ErrorResponseSchema(Schema):
    detail: str