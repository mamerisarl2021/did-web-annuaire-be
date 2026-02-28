"""
RBAC permission system.

Roles: SUPERADMIN (platform), ORG_ADMIN, ORG_MEMBER, AUDITOR (per-org).
Permissions are derived from role — no separate permission table.
"""

import enum

from src.common.exceptions import PermissionDeniedError
from src.common.types import Role


class Permission(str, enum.Enum):
    VIEW_DOCUMENTS = "VIEW_DOCUMENTS"
    MUTATE_DOCUMENTS = "MUTATE_DOCUMENTS"
    VIEW_CERTIFICATES = "VIEW_CERTIFICATES"
    MUTATE_CERTIFICATES = "MUTATE_CERTIFICATES"
    REVOKE_CERTIFICATES = "REVOKE_CERTIFICATES"
    MANAGE_MEMBERS = "MANAGE_MEMBERS"
    VIEW_AUDITS = "VIEW_AUDITS"


# ── Role → Permission mapping ───────────────────────────────────────────

ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    Role.ORG_ADMIN: {
        Permission.VIEW_DOCUMENTS,
        Permission.MUTATE_DOCUMENTS,
        Permission.VIEW_CERTIFICATES,
        Permission.MUTATE_CERTIFICATES,
        Permission.REVOKE_CERTIFICATES,
        Permission.MANAGE_MEMBERS,
        Permission.VIEW_AUDITS,
    },
    Role.ORG_MEMBER: {
        Permission.VIEW_DOCUMENTS,
        Permission.MUTATE_DOCUMENTS,
        Permission.VIEW_CERTIFICATES,
        Permission.MUTATE_CERTIFICATES,
        Permission.VIEW_AUDITS,
    },
    Role.AUDITOR: {
        Permission.VIEW_DOCUMENTS,
        Permission.VIEW_CERTIFICATES,
        Permission.VIEW_AUDITS,
    },
}


# ── Guards ───────────────────────────────────────────────────────────────


def require_superadmin(user) -> None:
    """Raise PermissionDeniedError if user is not a superadmin."""
    if not getattr(user, "is_superadmin", False):
        raise PermissionDeniedError("Superadmin access required.")


def require_permission(user, org_id, permission: Permission):
    """
    Verify the user has the given permission in the specified organization.

    Returns the active Membership instance so callers can use it
    (e.g., to get the org object).

    Superadmins bypass org membership checks.
    """
    from src.apps.organizations.models import Membership
    from src.common.types import MembershipStatus

    # Superadmins have all permissions everywhere
    if getattr(user, "is_superadmin", False):
        membership = (
            Membership.objects
            .filter(organization_id=org_id)
            .select_related("organization", "user")
            .first()
        )
        if membership:
            return membership
        return None

    membership = (
        Membership.objects
        .filter(
            user=user,
            organization_id=org_id,
            status=MembershipStatus.ACTIVE,
        )
        .select_related("organization", "user")
        .first()
    )

    if membership is None:
        raise PermissionDeniedError("You are not an active member of this organization.")

    role_perms = ROLE_PERMISSIONS.get(membership.role, set())
    if permission not in role_perms:
        raise PermissionDeniedError(
            f"Your role ({membership.role}) does not have {permission.value} permission."
        )

    return membership


def require_role(user, org_id, role: Role):
    """Verify the user has at least the specified role in the org."""
    from src.apps.organizations.models import Membership
    from src.common.types import MembershipStatus

    if getattr(user, "is_superadmin", False):
        return

    membership = (
        Membership.objects
        .filter(
            user=user,
            organization_id=org_id,
            status=MembershipStatus.ACTIVE,
        )
        .first()
    )

    if membership is None:
        raise PermissionDeniedError("You are not an active member of this organization.")

    if membership.role != role:
        raise PermissionDeniedError(f"Role {role} required, you have {membership.role}.")


def require_document_owner(user, document) -> None:
    """
    Verify the user is the creator of the DID document.

    Even org admins CANNOT edit documents they didn't create.
    They can only review (approve/reject).
    """
    if document.created_by_id != user.id:
        raise PermissionDeniedError(
            "Only the document creator can modify this document."
        )


def require_document_reviewer(user, org_id, document) -> None:
    """
    Verify the user can review (approve/reject) the DID document.
    Requirements:
      1. User must be an ORG_ADMIN in the organization.
      2. User must NOT be the document creator (can't review your own work).
    """
    require_permission(user, org_id, Permission.MANAGE_MEMBERS)

    if document.created_by_id == user.id:
        raise PermissionDeniedError(
            "You cannot review your own document."
        )