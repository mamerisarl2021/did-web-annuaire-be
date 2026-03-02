"""
DID Document API schemas.
"""

from typing import Any
from uuid import UUID

from ninja import Schema


# ── Request schemas ──────────────────────────────────────────────────────


class VerificationMethodSpec(Schema):
    certificate_id: UUID
    method_id_fragment: str
    relationships: list[str] = ["authentication", "assertionMethod"]
    method_type: str = "JsonWebKey2020"


class ServiceEndpointSpec(Schema):
    id: str
    type: str = "LinkedDomains"
    endpoint: str


class CreateDocumentSchema(Schema):
    label: str
    verification_methods: list[VerificationMethodSpec] = []
    service_endpoints: list[ServiceEndpointSpec] = []


class UpdateDraftSchema(Schema):
    verification_methods: list[VerificationMethodSpec] | None = None
    service_endpoints: list[ServiceEndpointSpec] | None = None


class AddVerificationMethodSchema(Schema):
    certificate_id: UUID
    method_id_fragment: str
    relationships: list[str] = ["authentication", "assertionMethod"]
    method_type: str = "JsonWebKey2020"


class ReviewSchema(Schema):
    comment: str = ""


class DeactivateSchema(Schema):
    reason: str = ""


# ── Response schemas ─────────────────────────────────────────────────────


class VerificationMethodResponse(Schema):
    id: UUID
    certificate_id: UUID
    certificate_label: str
    method_id_fragment: str
    method_type: str
    relationships: list[str]
    is_active: bool
    key_type: str
    key_curve: str


class DocListItemSchema(Schema):
    id: UUID
    label: str
    status: str
    did_uri: str
    owner_email: str
    owner_identifier: str
    created_by_email: str
    vm_count: int
    current_version_number: int | None
    has_pending_draft: bool = False
    created_at: str
    updated_at: str


class DocDetailSchema(Schema):
    id: UUID
    label: str
    status: str
    did_uri: str
    owner_email: str
    owner_identifier: str
    owner_id: UUID | None
    draft_content: Any | None
    content: Any | None
    created_by_email: str
    created_by_id: UUID | None
    submitted_by_email: str | None
    submitted_at: str | None
    reviewed_by_email: str | None
    reviewed_at: str | None
    review_comment: str
    current_version_number: int | None
    has_pending_draft: bool = False
    verification_methods: list[VerificationMethodResponse]
    verifiable_credential: Any | None
    created_at: str
    updated_at: str


class DocVersionSchema(Schema):
    id: UUID
    version_number: int
    content: Any
    signature: str
    published_at: str | None
    published_by_email: str


class MessageSchema(Schema):
    message: str


class ErrorSchema(Schema):
    detail: str