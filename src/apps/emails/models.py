from django.db import models

from src.common.models import BaseModel


class Email(BaseModel):
    class Status(models.TextChoices):
        READY = "READY", "Ready"
        SENDING = "SENDING", "Sending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    status = models.CharField(
        max_length=255, db_index=True, choices=Status.choices, default=Status.READY
    )

    to = models.EmailField()
    subject = models.CharField(max_length=255)

    html = models.TextField()
    plain_text = models.TextField()

    sent_at = models.DateTimeField(blank=True, null=True)
    task_name = models.CharField(max_length=100, blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
