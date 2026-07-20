from django.conf import settings
from django.db import models

from src.apps.files.utils import file_generate_upload_path
from src.common.models import BaseModel


class File(BaseModel):
    file = models.FileField(
        upload_to=file_generate_upload_path,
        blank=True,
        null=True,
    )
    original_file_name = models.TextField()
    file_name = models.CharField(max_length=255, unique=True)
    file_type = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField(default=0)

    upload_finished_at = models.DateTimeField(blank=True, null=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_files",
    )

    @property
    def is_valid(self) -> bool:
        return bool(self.upload_finished_at)

    @property
    def url(self) -> str:
        if not self.file:
            return ""
        # Absolute backend URL — relative /media/ paths resolve on the SPA origin otherwise.
        relative = self.file.url
        if relative.startswith(("http://", "https://")):
            return relative
        return f"{settings.PLATFORM_DOMAIN.rstrip('/')}{relative}"

    class Meta:
        db_table = "files"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.original_file_name} ({self.file_type})"
