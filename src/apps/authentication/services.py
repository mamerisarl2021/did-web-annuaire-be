"""
Authentication services.

Handles registration (with file uploads), OTP setup/verification,
logout (token blacklisting), and password reset.
"""

import base64
import io
import secrets
from datetime import timedelta

import pyotp
import qrcode
import structlog
from django.core.cache import cache
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone
from ninja_jwt.exceptions import TokenError
from ninja_jwt.tokens import RefreshToken

from src.apps.files.services import upload_document
from src.apps.users.models import User
from src.apps.users.services import activate_user, create_user, set_otp_secret
from src.common.exceptions import ValidationError

logger = structlog.get_logger(__name__)

RESET_TOKEN_PREFIX = "pwd_reset:"
RESET_TOKEN_TTL = timedelta(hours=1)


# ── Registration ────────────────────────────────────────────────────────


def register_user_and_org(
    *,
    # Organization fields (step 1)
    org_name: str,
    org_slug: str,
    org_description: str = "",
    org_type: str = "",
    org_country: str = "",
    org_address: str = "",
    org_email: str = "",
    authorization_document: UploadedFile,
    justification_document: UploadedFile | None = None,
    # User fields (step 2)
    email: str,
    full_name: str,
    password: str,
    phone: str = "",
    functions: str = "",
) -> User:
    """
    Register a new user and their organization.

    1. Creates the user (inactive).
    2. Uploads the documents.
    3. Creates the organization (PENDING_REVIEW).
    4. Creates the ORG_ADMIN membership (INVITED).
    """
    from src.apps.organizations import services as org_services
    from src.common.types import MembershipStatus, Role

    # 1. Create user
    user = create_user(
        email=email,
        full_name=full_name,
        password=password,
        phone=phone,
        functions=functions,
        is_active=False,
    )

    # 2. Upload documents
    auth_doc = upload_document(file=authorization_document, uploaded_by=user)
    just_doc = None
    if justification_document:
        just_doc = upload_document(file=justification_document, uploaded_by=user)

    # 3. Create organization
    org = org_services.create_organization(
        name=org_name,
        slug=org_slug,
        description=org_description,
        type=org_type,
        country=org_country,
        address=org_address,
        email=org_email,
        authorization_document=auth_doc,
        justification_document=just_doc,
        created_by=user,
    )

    # 4. Create membership
    org_services.create_membership(
        user=user,
        organization=org,
        role=Role.ORG_ADMIN,
        status=MembershipStatus.INVITED,
    )

    # TODO: Celery task — email superadmin about new registration
    logger.info("registration_complete", user_id=str(user.id), org_slug=org.slug)
    return user


# ── OTP Setup ───────────────────────────────────────────────────────────


def setup_otp(*, user: User) -> dict:
    if user.is_active and user.account_activated_at:
        raise ValidationError("Account is already activated.")

    secret = pyotp.random_base32()
    set_otp_secret(user=user, otp_secret=secret)

    totp = pyotp.TOTP(secret)
    otp_uri = totp.provisioning_uri(name=user.email, issuer_name="AnnuaireDID")

    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(otp_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    logger.info("otp_setup", user_id=str(user.id))

    return {
        "otp_uri": otp_uri,
        "qr_base64": f"data:image/png;base64,{qr_base64}",
    }


# ── OTP Verification ───────────────────────────────────────────────────


def verify_otp_and_activate(*, user: User, otp_code: str) -> User:
    if not user.otp_secret:
        raise ValidationError("OTP has not been set up. Call the setup endpoint first.")

    totp = pyotp.TOTP(user.otp_secret)
    if not totp.verify(otp_code, valid_window=1):
        raise ValidationError("Invalid OTP code.")

    user = activate_user(user=user)
    logger.info("otp_verified", user_id=str(user.id))
    return user


# ── Token generation ────────────────────────────────────────────────────


def generate_tokens_for_user(*, user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    refresh["email"] = user.email
    refresh["full_name"] = user.full_name
    refresh["is_superadmin"] = user.is_superadmin

    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


# ── Logout ──────────────────────────────────────────────────────────────


def logout_user(*, refresh_token: str) -> None:
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
        logger.info("user_logged_out", jti=token["jti"])
    except TokenError as e:
        raise ValidationError(f"Invalid or expired token: {e}")


# ── Password Reset ──────────────────────────────────────────────────────


def request_password_reset(*, email: str) -> None:
    """
    Generate a reset token in Redis and trigger a reset email.
    Always returns silently to prevent email enumeration.
    """
    from src.apps.users.selectors import get_user_by_email

    user = get_user_by_email(email=email.lower().strip())
    if user is None or not user.is_active:
        logger.info("password_reset_no_user", email=email)
        return

    token = secrets.token_urlsafe(48)
    cache_key = f"{RESET_TOKEN_PREFIX}{token}"
    cache.set(cache_key, str(user.id), timeout=int(RESET_TOKEN_TTL.total_seconds()))

    # TODO: Celery task — send password reset email
    logger.info("password_reset_token_generated", user_id=str(user.id), token=token)


def confirm_password_reset(*, token: str, new_password: str) -> None:
    from src.apps.users.selectors import get_user_by_id

    cache_key = f"{RESET_TOKEN_PREFIX}{token}"
    user_id = cache.get(cache_key)

    if user_id is None:
        raise ValidationError("Invalid or expired reset token.")

    user = get_user_by_id(user_id=user_id)
    if user is None:
        raise ValidationError("Invalid or expired reset token.")

    from django.contrib.auth.password_validation import validate_password

    try:
        validate_password(new_password, user)
    except Exception as e:
        raise ValidationError(str(e))

    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    cache.delete(cache_key)

    logger.info("password_reset_confirmed", user_id=str(user.id))


def change_password(*, user: User, old_password: str, new_password: str) -> None:
    if not user.check_password(old_password):
        raise ValidationError("Current password is incorrect.")

    from django.contrib.auth.password_validation import validate_password

    try:
        validate_password(new_password, user)
    except Exception as e:
        raise ValidationError(str(e))

    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    logger.info("password_changed", user_id=str(user.id))