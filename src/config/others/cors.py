"""
CORS configuration.

Uses django-cors-headers.
"""

from src.config.env import env

CORS_ALLOWED_ORIGINS = env.CORS_ALLOWED_ORIGINS

CORS_ALLOW_CREDENTIALS = True  # Required for httpOnly cookie auth

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]