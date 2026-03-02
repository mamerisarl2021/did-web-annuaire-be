"""
Static files, media files, and storage configuration.
"""

from src.config.env import BASE_DIR

# ── Static files ────────────────────────────────────────────────────────

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ── Media files ─────────────────────────────────────────────────────────

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "mediafiles"

# ── DID documents directory ─────────────────────────────────────────────
# Shared volume where did:web documents are served from by nginx.
# The Universal Registrar's driver-did-web also writes here.

DID_DOCUMENTS_ROOT = BASE_DIR / "data" / "dids"

STORAGES = {
    # ...
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}