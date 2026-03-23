"""
Points de terminaison de l'API d'authentification.

L'inscription est multipart (champs de formulaire + téléversements de fichiers).
La connexion se fait via NinjaJWTDefaultController de ninja_jwt (token/pair, token/refresh).
"""

from uuid import UUID

from django.http import HttpRequest
from ninja import File, Form, Router, UploadedFile
from ninja_jwt.authentication import JWTAuth

from src.apps.authentication import services as auth_services
from src.apps.users.services import update_user_profile
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
    UpdateProfileSchema,
    UserResponseSchema,
)
from src.apps.organizations.selectors import get_membership_by_invitation_token
from src.common.exceptions import NotFoundError

router = Router(tags=["Authentication"])


# ── Inscription (multipart) ─────────────────────────────────────────────


@router.post(
    "/register",
    response={
        201: RegisterResponseSchema,
        400: ErrorResponseSchema,
        409: ErrorResponseSchema,
    },
    summary="Register a new user and organization (multipart)",
)
def register(
    request: HttpRequest,
    # ── Champs d'organisation ──────
    org_name: str = Form(...),
    org_slug: str = Form(...),
    org_type: str = Form(""),
    org_description: str = Form(""),
    org_country: str = Form(""),
    org_address: str = Form(""),
    org_email: str = Form(""),
    authorization_document: UploadedFile = File(...),
    justification_document: UploadedFile = File(None),
    # ── Champs utilisateur ─────────
    email: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(""),
    phone: str = Form(""),
    functions: str = Form(""),
) -> dict:
    """
    Crée un nouvel utilisateur (inactif) et une organisation (PENDING_REVIEW).
    Accepte multipart/form-data avec des téléversements de fichiers PDF.
    Le mot de passe est optionnel — s'il n'est pas fourni, un espace réservé
    aléatoire inutilisable est généré. Le vrai mot de passe est toujours
    défini lors de l'activation du compte.
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
        password=password,  # le service génère un hash aléatoire si vide
        phone=phone,
        functions=functions,
    )
    return 201, {
        "message": "Registration submitted. Awaiting organization approval.",
        "user": user,
    }


# ── Configuration OTP ───────────────────────────────────────────────────


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


# ── Vérification OTP + Activation ───────────────────────────────────────


@router.post(
    "/activate/{invitation_token}/verify",
    response={
        200: ActivateVerifyResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
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

    # OTP verify + membership activation regroupés dans un seul service
    user, tokens = auth_services.verify_otp_activate_and_tokenize(
        membership=membership,
        otp_code=payload.otp_code,
        password=payload.password,
    )

    return 200, {
        "message": "Account activated successfully.",
        "access": tokens["access"],
        "refresh": tokens["refresh"],
        "user": user,
    }


# ── Déconnexion ─────────────────────────────────────────────────────────


@router.post(
    "/logout",
    response={200: LogoutResponseSchema, 400: ErrorResponseSchema},
    auth=JWTAuth(),
    summary="Logout — blacklist the refresh token",
)
def logout(request: HttpRequest, payload: LogoutRequestSchema):
    auth_services.logout_user(refresh_token=payload.refresh)
    return 200, {"message": "Successfully logged out."}


# ── Profil ──────────────────────────────────────────────────────────────


@router.get(
    "/me",
    response=UserResponseSchema,
    auth=JWTAuth(),
    summary="Get current user profile",
)
def me(request: HttpRequest):
    return request.auth


@router.patch(
    "/me",
    response={200: UserResponseSchema, 400: ErrorResponseSchema},
    auth=JWTAuth(),
    summary="Update current user profile (full_name, phone only — functions is admin-managed)",
)
def update_me(request: HttpRequest, payload: UpdateProfileSchema):
    """
    Met à jour les informations personnelles de l'utilisateur actuel.
    """

    user = update_user_profile(
        user=request.auth,
        full_name=payload.full_name,
        phone=payload.phone,
        email=payload.email,
        # functions intentionnellement exclus
    )
    return 200, user


# ── Réinitialisation de mot de passe (public) ───────────────────────────


@router.post(
    "/password-reset",
    response={200: MessageResponseSchema},
    summary="Request password reset email",
)
def password_reset_request(request: HttpRequest, payload: PasswordResetRequestSchema):
    auth_services.request_password_reset(email=payload.email)
    return 200, {
        "message": "If an account with that email exists, a reset link has been sent."
    }


@router.post(
    "/password-reset/confirm",
    response={200: MessageResponseSchema, 400: ErrorResponseSchema},
    summary="Confirm password reset with token",
)
def password_reset_confirm(request: HttpRequest, payload: PasswordResetConfirmSchema):
    auth_services.confirm_password_reset(
        token=payload.token, new_password=payload.new_password
    )
    return 200, {"message": "Password has been reset successfully."}


# ── Changement de mot de passe (authentifié) ────────────────────────────


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
