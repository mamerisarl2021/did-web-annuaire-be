"""
RBAC permission system for django-ninja.

Usage in apis.py:
    from ninja_jwt.authentication import JWTAuth
    from src.common.permissions import require_permission, Permission

    @router.get("/documents", auth=JWTAuth())
    def list_documents(request, org_id: UUID):
        membership = require_permission(request.auth, org_id, Permission.VIEW_DOCUMENTS)
        ...

Note: With JWTAuth, `request.auth` is the User instance (not `request.user`).
"""

from enum import StrEnum
from uuid import UUID

import structlog

from .exceptions import NotFoundError, PermissionDeniedError
from .types import Role

logger = structlog.get_logger(__name__)


# ── Permissions ─────────────────────────────────────────────────────────


class Permission(StrEnum):
    VIEW_DOCUMENTS = "view_documents"
    MUTATE_DOCUMENTS = "mutate_documents"
    VIEW_CERTIFICATES = "view_certificates"
    MUTATE_CERTIFICATES = "mutate_certificates"
    REVOKE_CERTIFICATES = "revoke_certificates"
    MANAGE_MEMBERS = "manage_members"
    VIEW_AUDITS = "view_audits"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ORG_ADMIN: {p for p in Permission},
    Role.ORG_MEMBER: {
        Permission.VIEW_DOCUMENTS,
        Permission.MUTATE_DOCUMENTS,
        Permission.VIEW_CERTIFICATES,
        Permission.MUTATE_CERTIFICATES,
    },
    Role.AUDITOR: {
        Permission.VIEW_DOCUMENTS,
        Permission.VIEW_CERTIFICATES,
        Permission.VIEW_AUDITS,
    },
}


# ── Permission checks ──────────────────────────────────────────────────


def require_superadmin(user) -> None:
    """
    Raise if user is not a superadmin.
    `user` is request.auth from JWTAuth.
    """
    if not user or not user.is_superadmin:
        raise PermissionDeniedError("Superadmin access required.")


def require_role(user, org_id: UUID, roles: list[Role]):
    """
    Check that user has one of the required roles in the given org.
    Returns the Membership instance.
    """
    from src.apps.organizations.selectors import get_active_membership

    membership = get_active_membership(user=user, organization_id=org_id)
    if membership is None:
        raise NotFoundError("Organization not found or you are not an active member.")

    if Role(membership.role) not in roles:
        raise PermissionDeniedError(
            f"Requires one of {[r.value for r in roles]}, you have {membership.role}."
        )
    return membership


def require_permission(user, org_id: UUID, permission: Permission):
    """
    Check that user's role in the org grants the specified permission.
    Returns the Membership instance.
    """
    from src.apps.organizations.selectors import get_active_membership

    membership = get_active_membership(user=user, organization_id=org_id)
    if membership is None:
        raise NotFoundError("Organization not found or you are not an active member.")

    role = Role(membership.role)
    if permission not in ROLE_PERMISSIONS.get(role, set()):
        raise PermissionDeniedError(
            f"Permission '{permission}' not granted for role '{role}'."
        )
    return membership