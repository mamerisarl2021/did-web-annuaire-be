"""
File services — handles upload, validation, and deletion.
"""

import structlog
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from src.apps.files.models import File
from src.apps.files.utils import file_generate_name
from src.common.exceptions import ValidationError

logger = structlog.get_logger(__name__)

# ── Allowed MIME types per context ──────────────────────────────────────

ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
}

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

ALLOWED_CERTIFICATE_TYPES = {
    "application/x-pem-file",
    "application/x-x509-ca-cert",
    "application/pkix-cert",
    "text/plain",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _detect_mime_type(file: UploadedFile) -> str:
    """Detect MIME type from the uploaded file."""
    import mimetypes

    content_type = file.content_type or ""
    if not content_type:
        guessed, _ = mimetypes.guess_type(file.name or "")
        content_type = guessed or "application/octet-stream"
    return content_type


def _validate_file(
    file: UploadedFile,
    allowed_types: set[str] | None = None,
    max_size: int = MAX_FILE_SIZE,
) -> str:
    """
    Validate an uploaded file. Returns the detected MIME type.

    Raises:
        ValidationError: If file is too large or wrong type.
    """
    if file.size and file.size > max_size:
        max_mb = max_size / (1024 * 1024)
        raise ValidationError(
            f"File too large ({file.size} bytes). Maximum is {max_mb:.0f} MB."
        )

    content_type = _detect_mime_type(file)

    if allowed_types and content_type not in allowed_types:
        raise ValidationError(
            f"File type '{content_type}' not allowed. "
            f"Accepted: {', '.join(sorted(allowed_types))}"
        )

    return content_type

@transaction.atomic
def upload_file(
    *,
    file: UploadedFile,
    uploaded_by=None,
    allowed_types: set[str] | None = None,
    max_size: int = MAX_FILE_SIZE,
) -> File:
    """
    Upload and persist a file.

    Returns the created File instance.
    """
    content_type = _validate_file(file, allowed_types, max_size)
    unique_name = file_generate_name(file.name or "upload")

    file_instance = File(
        original_file_name=file.name or "unknown",
        file_name=unique_name,
        file_type=content_type,
        file_size=file.size or 0,
        uploaded_by=uploaded_by,
        upload_finished_at=timezone.now(),
    )
    file_instance.file.save(unique_name, file, save=False)
    file_instance.save()

    logger.info(
        "file_uploaded",
        file_id=str(file_instance.id),
        original_name=file_instance.original_file_name,
        file_type=content_type,
        size=file.size,
    )
    return file_instance

@transaction.atomic
def upload_document(*, file: UploadedFile, uploaded_by=None) -> File:
    """Upload a document file (PDF only)."""
    return upload_file(
        file=file,
        uploaded_by=uploaded_by,
        allowed_types=ALLOWED_DOCUMENT_TYPES,
    )

@transaction.atomic
def upload_certificate_file(*, file: UploadedFile, uploaded_by=None) -> File:
    """Upload a certificate file (PEM/DER)."""
    return upload_file(
        file=file,
        uploaded_by=uploaded_by,
        allowed_types=ALLOWED_CERTIFICATE_TYPES,
    )

@transaction.atomic
def delete_file(*, file_instance: File) -> None:
    """Delete a file from storage and the database."""
    file_id = str(file_instance.id)
    if file_instance.file:
        file_instance.file.delete(save=False)
    file_instance.delete()
    logger.info("file_deleted", file_id=file_id)
