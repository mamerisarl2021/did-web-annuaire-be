from django.http import HttpRequest
from ninja import Router
import jwt
from datetime import datetime, timedelta, UTC
from django.conf import settings

from src.apps.apiclients.models import MachineClient
from src.apps.apiclients.schemas import MachineTokenRequestSchema, MachineTokenResponseSchema
from src.common.exceptions import ValidationError
from src.common.throttling import m2m_token_throttle


router = Router(tags=["API Clients (M2M)"])


# ── 1. Token Endpoint ────────────────────────────────────────────────────────

@router.post(
    "/token",
    response=MachineTokenResponseSchema,
    summary="Get M2M Access Token",
    auth=None,
    throttle=m2m_token_throttle,
)
def get_machine_token(request: HttpRequest, payload: MachineTokenRequestSchema):
    try:
        client = MachineClient.objects.get(client_id=payload.client_id, is_active=True)
    except MachineClient.DoesNotExist:
        raise ValidationError("Invalid client_id or client_secret")

    if not client.verify_secret(payload.client_secret):
        raise ValidationError("Invalid client_id or client_secret")

    expires_in = 86400  # 24 hours
    token_payload = {
        "client_id": client.client_id,
        "type": "machine",
        "exp": datetime.now(UTC) + timedelta(seconds=expires_in),
        "iat": datetime.now(UTC)
    }

    token = jwt.encode(token_payload, settings.SECRET_KEY, algorithm="HS256")

    return {
        "access_token": token,
        "expires_in": expires_in,
        "token_type": "Bearer"
    }
