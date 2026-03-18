"""
Org Admin API schemas.

Endpoints scoped to the current user's organization(s).
"""

from uuid import UUID

from ninja import Schema


# ── Request ─────────────────────────────────────────────────────────────


class InviteMemberSchema(Schema):
    email: str
    full_name: str = ""
    phone: str = ""
    functions: str = ""
    has_audit_access: bool = False


class ChangeMemberRoleSchema(Schema):
    role: str


class UpdateMemberSchema(Schema):
    full_name: str | None = None
    phone: str | None = None
    functions: str | None = None
    has_audit_access: bool | None = None


# ── Response ────────────────────────────────────────────────────────────


class OrgSummarySchema(Schema):
    id: UUID
    name: str
    slug: str
    type: str
    status: str
    member_count: int = 0
    document_count: int = 0
    certificate_count: int = 0


class UpdateOrgSchema(Schema):
    name: str | None = None
    type: str | None = None
    email: str | None = None
    country: str | None = None
    address: str | None = None
    description: str | None = None


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
    created_at: str
    member_count: int = 0
    document_count: int = 0
    certificate_count: int = 0


class MemberSchema(Schema):
    id: UUID
    user_id: UUID
    email: str
    full_name: str
    phone: str
    functions: str
    role: str
    status: str
    is_active: bool
    invited_by_email: str | None = None
    activated_at: str | None = None
    created_at: str


class OrgStatsSchema(Schema):
    total_members: int
    active_members: int
    invited_members: int
    total_documents: int
    draft_documents: int
    signed_documents: int
    published_documents: int
    total_certificates: int
    my_role: str = ""
    can_view_audits: bool = False


class AuditLogSchema(Schema):
    id: UUID
    action: str
    resource_type: str
    resource_id: UUID
    description: str
    metadata: dict
    actor_email: str
    created_at: str
    ip_address: str | None = None


class MessageSchema(Schema):
    message: str


class ErrorSchema(Schema):
    detail: str
