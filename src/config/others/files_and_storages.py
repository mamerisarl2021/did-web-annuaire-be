"""
Static files, media files, and storage configuration.
"""

import copy
from django.conf import settings
from src.config.env import BASE_DIR
from src.config.env import env
from src.xlib.enum_to_env import enum_to_env
from src.xlib.enums import StorageEnum

STATIC_ROOT = BASE_DIR / "static_root"
MEDIA_ROOT = BASE_DIR / "media"

# STATICFILES_DIRS = [
#     BASE_DIR / "staticfiles"
# ]  # Auto-discovers app static/ dirs if empty list

# ── DID documents directory ─────────────────────────────────────────────
# Shared volume where did:web documents are served from by nginx.
# The Universal Registrar's driver-did-web also writes here.

DID_DOCUMENTS_ROOT = BASE_DIR / "data" / "dids"

STORAGE_STRATEGY = enum_to_env(StorageEnum, env.STORAGE)

if STORAGE_STRATEGY == StorageEnum.LOCAL:
    STATIC_URL = "/static/"
    MEDIA_URL = "/media/"

    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

elif STORAGE_STRATEGY == StorageEnum.S3:
    STATIC_URL = (
        f"{env.S3_ENDPOINT_URL}/{env.S3_BUCKET_NAME}/static/"
    )
    MEDIA_URL = f"{env.S3_ENDPOINT_URL}/{env.S3_BUCKET_NAME}/media/"

    _S3_BASE_OPTIONS = {
        "access_key": env.S3_ACCESS_KEY,
        "secret_key": env.S3_SECRET_KEY,
        "bucket_name": env.S3_BUCKET_NAME,
        "endpoint_url": env.S3_ENDPOINT_URL,
        "signature_version": "s3v4",
        "addressing_style": "path",
        "querystring_auth": True,
        "querystring_expire": 3600,
        "region_name": "us-east-1",
        "client_config": {
            "request_checksum_calculation": "when_required",
            "response_checksum_validation": "when_required",
        },
    }

    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **copy.deepcopy(_S3_BASE_OPTIONS),
                "location": "media_files",
            },
        },
        "staticfiles": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **copy.deepcopy(_S3_BASE_OPTIONS),
                "location": "static_root",
            },
        },
    }

else:
    raise RuntimeError(f"Unknown storage strategy {STORAGE_STRATEGY!r}")

# Prevent manifest errors from crashing the app
WHITENOISE_MANIFEST_STRICT = False
