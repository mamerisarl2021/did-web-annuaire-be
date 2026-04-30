from ninja import Schema

class MachineTokenRequestSchema(Schema):
    client_id: str
    client_secret: str

class MachineTokenResponseSchema(Schema):
    access_token: str
    expires_in: int
    token_type: str = "Bearer"