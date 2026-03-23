"""
Static files, media files, and storage configuration.
"""

from src.config.env import BASE_DIR

# ── Static files ────────────────────────────────────────────────────────

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static_root"

STATICFILES_DIRS = [
    BASE_DIR / "staticfiles"
]  # Auto-discovers app static/ dirs if empty list

# ── Media files ─────────────────────────────────────────────────────────

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "mediafiles"

# ── DID documents directory ─────────────────────────────────────────────
# Shared volume where did:web documents are served from by nginx.
# The Universal Registrar's driver-did-web also writes here.

DID_DOCUMENTS_ROOT = BASE_DIR / "data" / "dids"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Prevent manifest errors from crashing the app
WHITENOISE_MANIFEST_STRICT = False
