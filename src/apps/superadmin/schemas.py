"""
Superadmin API schemas.
"""

from uuid import UUID

from ninja import Schema


# ── Request ─────────────────────────────────────────────────────────────


class OrgApproveSchema(Schema):
    pass  # No body needed — action is in the URL


class OrgRejectSchema(Schema):
    reason: str = ""


class OrgSuspendSchema(Schema):
    reason: str = ""


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