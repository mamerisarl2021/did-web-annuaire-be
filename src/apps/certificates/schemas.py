"""
Certificate API schemas.
"""

from uuid import UUID

from ninja import Schema


# ── Request ─────────────────────────────────────────────────────────────


class CertUploadSchema(Schema):
    label: str
    p12_password: str | None = None


class CertRevokeSchema(Schema):
    reason: str = ""


# ── Response ────────────────────────────────────────────────────────────


class CertVersionSummarySchema(Schema):
    id: UUID
    version_number: int
    key_type: str
    key_curve: str
    subject_dn: str
    issuer_dn: str
    serial_number: str
    not_valid_before: str | None = None
    not_valid_after: str | None = None
    fingerprint_sha256: str
    is_current: bool
    created_at: str


class CertVersionDetailSchema(CertVersionSummarySchema):
    public_key_jwk: dict
    key_size: int | None = None
    uploaded_by_email: str = ""
    file_name: str = ""


class CertListItemSchema(Schema):
    id: UUID
    label: str
    status: str
    key_type: str
    key_curve: str
    subject_dn: str
    fingerprint_sha256: str
    not_valid_after: str | None = None
    created_by_email: str = ""
    created_at: str
    version_count: int = 1


class CertDetailSchema(Schema):
    id: UUID
    label: str
    status: str
    created_by_email: str = ""
    created_by_id: UUID | None = None
    created_at: str
    current_version: CertVersionDetailSchema | None = None
    version_count: int = 0
    linked_documents: int = 0


class MessageSchema(Schema):
    message: str


class ErrorSchema(Schema):
    detail: str