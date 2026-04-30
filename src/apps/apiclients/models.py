from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from src.common.models import BaseModel


class MachineClient(BaseModel):
    name = models.CharField(max_length=255, help_text="Nom du système client (ex: Port Platform)")
    client_id = models.CharField(max_length=100, unique=True, help_text="Identifiant unique du client")
    client_secret_hash = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "machine_clients"

    def set_secret(self, raw_secret: str):
        self.client_secret_hash = make_password(raw_secret)

    def verify_secret(self, raw_secret: str) -> bool:
        return check_password(raw_secret, self.client_secret_hash)

    def __str__(self):
        return f"{self.name} ({self.client_id})"