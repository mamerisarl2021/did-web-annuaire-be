"""
Superadmin API schemas.
"""

from uuid import UUID

from ninja import Schema

# ── Request ─────────────────────────────────────────────────────────────


class OrgRejectSchema(Schema):
    reason: str = ""


class OrgSuspendSchema(Schema):
    reason: str = ""


class AddUserToOrgSchema(Schema):
    org_id: UUID
    role: str


# ── Response ────────────────────────────────────────────────────────────


class FileResponseSchema(Schema):
    id: UUID
    original_file_name: str
    file_type: str
    file_size: int
    url: str


class AdminUserSchema(Schema):
    id: UUID
    email: str
    full_name: str
    phone: str
    functions: str
    is_active: bool


class OrgListItemSchema(Schema):
    id: UUID
    name: str
    slug: str
    type: str
    country: str
    email: str
    status: str
    created_at: str
    admin_email: str | None = None


class UserMembershipSchema(Schema):
    id: UUID
    org_id: UUID
    org_name: str
    role: str
    status: str


class SAUserSchema(Schema):
    id: UUID
    email: str
    full_name: str
    phone: str
    is_active: bool
    created_at: str
    memberships: list[UserMembershipSchema] = []


class SAAuditLogSchema(Schema):
    id: UUID
    actor_email: str
    action: str
    resource_type: str
    resource_id: UUID | None = None
    description: str
    created_at: str
    organization_name: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    metadata: dict | None = None


class SADIDDocumentSchema(Schema):
    id: UUID
    label: str
    organization_name: str
    org_slug: str
    owner_email: str
    owner_identifier: str
    status: str
    created_at: str
    updated_at: str


class SACertificateSchema(Schema):
    id: UUID
    label: str
    organization_name: str
    org_slug: str
    status: str
    created_at: str
    key_type: str | None = None
    not_valid_after: str | None = None


class OrgDetailSchema(Schema):
    id: UUID
    name: str
    slug: str
    type: str
    description: str
    country: str
    address: str
    email: str
    status: str
    rejection_reason: str
    created_at: str
    reviewed_at: str | None = None
    authorization_document: FileResponseSchema | None = None
    justification_document: FileResponseSchema | None = None
    admin_user: AdminUserSchema | None = None
    member_count: int = 0

    @staticmethod
    def resolve_reviewed_at(obj) -> str | None:
        return obj.reviewed_at.isoformat() if obj.reviewed_at else None


class MessageSchema(Schema):
    message: str


class ErrorSchema(Schema):
    detail: str


class DashboardStatsSchema(Schema):
    pending_count: int
    approved_count: int
    rejected_count: int
    suspended_count: int
    total_users: int
    active_users: int
    total_did_documents: int
    total_certificates: int
