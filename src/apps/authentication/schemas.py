"""
Schémas d'authentification.
"""

from uuid import UUID

from ninja import Schema
from ninja_jwt.schema import TokenObtainPairInputSchema
from ninja_jwt.tokens import RefreshToken
from pydantic import model_validator

from src.apps.users.models import User

# ── Obtention de jeton personnalisée (connexion) ────────────────────────


class CustomTokenObtainPairInput(TokenObtainPairInputSchema):
    @classmethod
    def get_token(cls, user: User) -> RefreshToken:
        if not user.is_superadmin:
            from ninja_jwt.exceptions import AuthenticationFailed

            from src.apps.organizations.models import Membership
            from src.common.types import MembershipStatus, OrgStatus

            active_memberships = Membership.objects.filter(
                user=user,
                status=MembershipStatus.ACTIVE
            ).select_related("organization")

            if active_memberships.exists():
                all_suspended = all(
                    m.organization.status == OrgStatus.SUSPENDED
                    for m in active_memberships
                )
                if all_suspended:
                    raise AuthenticationFailed("Your organization's account is suspended. Please contact support.")

        token = super().get_token(user)
        token["email"] = user.email
        token["full_name"] = user.full_name
        token["is_superadmin"] = user.is_superadmin
        return token


# ── Schémas de requête ────────────────────────────────────────────────────


class ActivateVerifyRequestSchema(Schema):
    otp_code: str
    password: str
    confirm_password: str

    @model_validator(mode="after")
    def passwords_must_match(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


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


class UpdateProfileSchema(Schema):
    """
    Permet aux utilisateurs de mettre à jour leurs informations personnelles.
    """

    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    functions: str | None = None


# ── Schémas de réponse ────────────────────────────────────────────────────


class UserResponseSchema(Schema):
    id: UUID
    email: str
    full_name: str
    phone: str
    functions: str
    is_active: bool
    is_superadmin: bool
    role: str | None = None
    can_view_audits: bool = False
    activation_method: str
    account_activated_at: str | None = None
    created_at: str

    @staticmethod
    def resolve_can_view_audits(obj) -> bool:
        if obj.is_superadmin:
            return True
            
        from src.apps.organizations.models import Membership
        from src.common.types import MembershipStatus
        
        # Determine from the user's active memberships
        membership = Membership.objects.filter(
            user=obj, 
            status=MembershipStatus.ACTIVE
        ).first()
        
        if membership:
            return membership.can_view_audits
        return False

    @staticmethod
    def resolve_role(obj) -> str | None:
        if obj.is_superadmin:
            return "SUPERADMIN"
            
        from src.apps.organizations.models import Membership
        from src.common.types import MembershipStatus
        
        membership = Membership.objects.filter(
            user=obj, 
            status=MembershipStatus.ACTIVE
        ).first()
        
        if membership:
            return membership.role
        return None

    @staticmethod
    def resolve_account_activated_at(obj) -> str | None:
        return (
            obj.account_activated_at.isoformat() if obj.account_activated_at else None
        )

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
