"""
Authentication API endpoints.

Register is multipart (Form fields + file uploads).
Login is via ninja_jwt's NinjaJWTDefaultController (token/pair, token/refresh).
"""

from uuid import UUID

from django.http import HttpRequest
from ninja import File, Form, Router, UploadedFile
from ninja_jwt.authentication import JWTAuth

from src.apps.authentication import services as auth_services
from src.apps.authentication.schemas import (
    ActivateSetupResponseSchema,
    ActivateVerifyRequestSchema,
    ActivateVerifyResponseSchema,
    ErrorResponseSchema,
    LogoutRequestSchema,
    LogoutResponseSchema,
    MessageResponseSchema,
    PasswordChangeSchema,
    PasswordResetConfirmSchema,
    PasswordResetRequestSchema,
    RegisterResponseSchema,
    UserResponseSchema,
)
from src.apps.organizations.selectors import get_membership_by_invitation_token
from src.common.exceptions import NotFoundError

router = Router(tags=["Authentication"])


# ── Register (multipart) ───────────────────────────────────────────────


@router.post(
    "/register",
    response={201: RegisterResponseSchema, 400: ErrorResponseSchema, 409: ErrorResponseSchema},
    summary="Register a new user and organization (multipart)",
)
def register(
    request: HttpRequest,
    # ── Organization fields (step 1 of the frontend form) ───────────
    org_name: str = Form(...),
    org_slug: str = Form(...),
    org_type: str = Form(""),
    org_description: str = Form(""),
    org_country: str = Form(""),
    org_address: str = Form(""),
    org_email: str = Form(""),
    authorization_document: UploadedFile = File(...),
    justification_document: UploadedFile = File(None),
    # ── User fields (step 2 of the frontend form) ──────────────────
    email: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    phone: str = Form(""),
    functions: str = Form(""),
):
    """
    Creates a new user (inactive) and an organization (PENDING_REVIEW).
    Accepts multipart/form-data with PDF file uploads.
    """
    user = auth_services.register_user_and_org(
        org_name=org_name,
        org_slug=org_slug,
        org_type=org_type,
        org_description=org_description,
        org_country=org_country,
        org_address=org_address,
        org_email=org_email,
        authorization_document=authorization_document,
        justification_document=justification_document,
        email=email,
        full_name=full_name,
        password=password,
        phone=phone,
        functions=functions,
    )
    return 201, {
        "message": "Registration submitted. Awaiting organization approval.",
        "user": user,
    }


# ── OTP Setup ───────────────────────────────────────────────────────────


@router.get(
    "/activate/{invitation_token}",
    response={200: ActivateSetupResponseSchema, 404: ErrorResponseSchema},
    summary="Get OTP setup (secret + QR code)",
)
def activate_setup(request: HttpRequest, invitation_token: UUID):
    membership = get_membership_by_invitation_token(token=invitation_token)
    if membership is None:
        raise NotFoundError("Invalid or expired activation link.")

    result = auth_services.setup_otp(user=membership.user)

    return 200, {
        "otp_uri": result["otp_uri"],
        "qr_base64": result["qr_base64"],
        "message": "Scan the QR code with your authenticator app, then verify with a code.",
    }


# ── OTP Verify + Activate ──────────────────────────────────────────────


@router.post(
    "/activate/{invitation_token}/verify",
    response={200: ActivateVerifyResponseSchema, 400: ErrorResponseSchema, 404: ErrorResponseSchema},
    summary="Verify OTP code and activate account",
)
def activate_verify(
    request: HttpRequest,
    invitation_token: UUID,
    payload: ActivateVerifyRequestSchema,
):
    membership = get_membership_by_invitation_token(token=invitation_token)
    if membership is None:
        raise NotFoundError("Invalid or expired activation link.")

    user = auth_services.verify_otp_and_activate(
        user=membership.user,
        otp_code=payload.otp_code,
    )

    from src.apps.organizations.services import activate_membership
    activate_membership(membership=membership)

    tokens = auth_services.generate_tokens_for_user(user=user)

    return 200, {
        "message": "Account activated successfully.",
        "access": tokens["access"],
        "refresh": tokens["refresh"],
        "user": user,
    }


# ── Logout ──────────────────────────────────────────────────────────────


@router.post(
    "/logout",
    response={200: LogoutResponseSchema, 400: ErrorResponseSchema},
    auth=JWTAuth(),
    summary="Logout — blacklist the refresh token",
)
def logout(request: HttpRequest, payload: LogoutRequestSchema):
    auth_services.logout_user(refresh_token=payload.refresh)
    return 200, {"message": "Successfully logged out."}


# ── Profile ─────────────────────────────────────────────────────────────


@router.get(
    "/me",
    response=UserResponseSchema,
    auth=JWTAuth(),
    summary="Get current user profile",
)
def me(request: HttpRequest):
    return request.auth


# ── Password Reset (public) ─────────────────────────────────────────────


@router.post(
    "/password-reset",
    response={200: MessageResponseSchema},
    summary="Request password reset email",
)
def password_reset_request(request: HttpRequest, payload: PasswordResetRequestSchema):
    auth_services.request_password_reset(email=payload.email)
    return 200, {"message": "If an account with that email exists, a reset link has been sent."}


@router.post(
    "/password-reset/confirm",
    response={200: MessageResponseSchema, 400: ErrorResponseSchema},
    summary="Confirm password reset with token",
)
def password_reset_confirm(request: HttpRequest, payload: PasswordResetConfirmSchema):
    auth_services.confirm_password_reset(token=payload.token, new_password=payload.new_password)
    return 200, {"message": "Password has been reset successfully."}


# ── Password Change (authenticated) ─────────────────────────────────────


@router.post(
    "/password-change",
    response={200: MessageResponseSchema, 400: ErrorResponseSchema},
    auth=JWTAuth(),
    summary="Change password (requires current password)",
)
def password_change(request: HttpRequest, payload: PasswordChangeSchema):
    auth_services.change_password(
        user=request.auth,
        old_password=payload.old_password,
        new_password=payload.new_password,
    )
    return 200, {"message": "Password changed successfully."}