"""
JWT configuration for ninja_jwt.

Access token: short-lived (default 30 min).
Refresh token: longer-lived (default 7 days), rotated on use, old ones blacklisted.
"""

from datetime import timedelta

from src.config.env import env

NINJA_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.JWT_ACCESS_TOKEN_LIFETIME_MINUTES),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.JWT_REFRESH_TOKEN_LIFETIME_DAYS),

    # Rotation: issue a new refresh token on every refresh, blacklist the old one
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,

    "ALGORITHM": "HS256",
    "SIGNING_KEY": env.jwt_signing_key,

    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",

    # Custom claims — we embed user_id and email in the token
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",

    # Token classes
    "AUTH_TOKEN_CLASSES": ("ninja_jwt.tokens.AccessToken",),
    "TOKEN_OBTAIN_PAIR_INPUT_SCHEMA": "src.apps.authentication.schemas.CustomTokenObtainPairInput",
    "TOKEN_OBTAIN_PAIR_REFRESH_INPUT_SCHEMA": "ninja_jwt.schema.TokenRefreshInputSchema",
}