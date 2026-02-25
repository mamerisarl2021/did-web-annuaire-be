# src/common/models.py

import uuid

from django.db import models
from django.utils import timezone

class BaseModel(models.Model):
    id = models.UUIDField(
        default=uuid.uuid4,
        primary_key = True,
        editable=False)

    created_at = models.DateTimeField(
        default=timezone.now,
        db_index=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True