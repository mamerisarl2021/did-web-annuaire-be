from django.http import HttpRequest
from ninja.security import HttpBearer
import jwt
from django.conf import settings
from src.apps.apiclients.models import MachineClient


class MachineJWTAuth(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str):
        try:
            # Decode the token using the Django secret key
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"]
            )

            # Ensure this is specifically a machine token
            if payload.get("type") != "machine":
                return None

            client_id = payload.get("client_id")
            if not client_id:
                return None

            client = MachineClient.objects.get(client_id=client_id, is_active=True)
            return client  # This attaches the client to request.auth

        except (jwt.PyJWTError, MachineClient.DoesNotExist):
            return None