"""
Org Admin API schemas.

Endpoints scoped to the current user's organization(s).
"""

from uuid import UUID

from ninja import Schema


# ── Request ─────────────────────────────────────────────────────────────


class InviteMemberSchema(Schema):
    email: str
    role: str  # ORG_MEMBER or AUDITOR
    full_name: str = ""


class ChangeMemberRoleSchema(Schema):
    role: str


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
    total_certificates: int


class MessageSchema(Schema):
    message: str


class ErrorSchema(Schema):
    detail: str
