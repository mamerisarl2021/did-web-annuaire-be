"""
File upload path utilities.
"""

import uuid
from pathlib import Path


def file_generate_upload_path(instance, filename: str) -> str:
    """
    Generate a unique upload path for a file.
    Structure: uploads/{app_label}/{year}/{month}/{uuid}.{ext}
    """
    from django.utils import timezone

    ext = Path(filename).suffix.lower()
    now = timezone.now()
    unique_name = f"{uuid.uuid4().hex}{ext}"

    app_label = "general"
    if hasattr(instance, "_meta"):
        app_label = instance._meta.app_label

    return f"uploads/{app_label}/{now.year}/{now.month:02d}/{unique_name}"


def file_generate_name(original_filename: str) -> str:
    """Generate a unique filename preserving the original extension."""
    ext = Path(original_filename).suffix.lower()
    return f"{uuid.uuid4().hex}{ext}"
