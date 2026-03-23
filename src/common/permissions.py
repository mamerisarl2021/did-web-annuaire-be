"""
Système de permissions RBAC.

Rôles : SUPERADMIN (plateforme), ORG_ADMIN, ORG_MEMBER, AUDITOR.
Les permissions dérivent du rôle — pas de table séparée.

L'accès à l'audit est contrôlé par le drapeau has_audit_access sur Membership
plutôt que par un rôle AUDITOR. ORG_ADMIN a toujours l'accès à l'audit.
Le rôle AUDITOR est conservé pour la compatibilité descendante mais est
fonctionnellement équivalent à ORG_MEMBER + has_audit_access=True.
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


# ── Mappage Rôle → Permission ───────────────────────────────────────────
# VIEW_AUDITS n'est plus dans les mappages de base — résolu dynamiquement
# via membership.has_audit_access ou le rôle ORG_ADMIN.

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
    },
    # Compatibilité : rôle AUDITOR = lecture seule + accès à l'audit
    Role.AUDITOR: {
        Permission.VIEW_DOCUMENTS,
        Permission.VIEW_CERTIFICATES,
        Permission.VIEW_AUDITS,
    },
}


def _get_effective_permissions(membership) -> set[Permission]:
    """
    Calcule l'ensemble des permissions effectives pour une adhésion,
    en tenant compte du drapeau has_audit_access.
    """
    base = ROLE_PERMISSIONS.get(membership.role, set()).copy()

    # Accorde VIEW_AUDITS si le drapeau est défini, quel que soit le rôle
    if getattr(membership, "has_audit_access", False):
        base.add(Permission.VIEW_AUDITS)

    return base


# ── Gardes ───────────────────────────────────────────────────────────────


def require_superadmin(user) -> None:
    """Lève PermissionDeniedError si l'utilisateur n'est pas superadmin."""
    if not getattr(user, "is_superadmin", False):
        raise PermissionDeniedError("Superadmin access required.")


def require_permission(user, org_id, permission: Permission):
    """
    Vérifie que l'utilisateur a la permission donnée dans l'organisation spécifiée.

    Retourne l'instance Membership active pour que les appelants puissent l'utiliser
    (ex. pour obtenir l'objet organisation).

    Les superadmins contournent les vérifications d'adhésion.
    """
    from src.apps.organizations.models import Membership, Organization
    from src.common.types import MembershipStatus

    # ── CORRECTION : Contournement Superadmin ───────────────────────
    # L'ancien code retournait l'adhésion d'un membre aléatoire de l'org,
    # ce qui entraînait une mauvaise personne pour membership.user et
    # un crash possible d'AttributeError pour membership.organization.
    #
    # Nouveau : essaie d'abord la propre adhésion du superadmin ; s'il n'en
    # a pas, construit une adhésion Memory (non sauvegardée) synthétique pour que 
    # les appelants obtiennent des références valides pour .organization et .user.
    if getattr(user, "is_superadmin", False):
        org = Organization.objects.filter(id=org_id).first()
        if org is None:
            raise PermissionDeniedError("Organization not found.")

        own_membership = (
            Membership.objects.filter(user=user, organization_id=org_id)
            .select_related("organization", "user")
            .first()
        )
        if own_membership:
            return own_membership

        # Adhésion synthétique (non sauvegardée) pour la cohérence de l'API
        synthetic = Membership(
            user=user,
            organization=org,
            role=Role.ORG_ADMIN,
            status=MembershipStatus.ACTIVE,
            has_audit_access=True,
        )
        synthetic.organization = org
        synthetic.user = user
        return synthetic

    membership = (
        Membership.objects.filter(
            user=user,
            organization_id=org_id,
            status=MembershipStatus.ACTIVE,
        )
        .select_related("organization", "user")
        .first()
    )

    if membership is None:
        raise PermissionDeniedError(
            "You are not an active member of this organization."
        )

    effective_perms = _get_effective_permissions(membership)
    if permission not in effective_perms:
        raise PermissionDeniedError(
            f"Your role ({membership.role}) does not have {permission.value} permission."
        )

    return membership


def require_role(user, org_id, role: Role):
    """Vérifie que l'utilisateur a au moins le rôle spécifié dans l'org."""
    from src.apps.organizations.models import Membership
    from src.common.types import MembershipStatus

    if getattr(user, "is_superadmin", False):
        return

    membership = Membership.objects.filter(
        user=user,
        organization_id=org_id,
        status=MembershipStatus.ACTIVE,
    ).first()

    if membership is None:
        raise PermissionDeniedError(
            "You are not an active member of this organization."
        )

    if membership.role != role:
        raise PermissionDeniedError(
            f"Role {role} required, you have {membership.role}."
        )


def require_document_owner(user, document) -> None:
    """
    Vérifie que l'utilisateur est le propriétaire du document DID.

    Utilise owner_id (le champ de propriétaire canonique), pas created_by_id.
    Même les administrateurs d'organisation NE PEUVENT PAS éditer des
    documents qu'ils n'ont pas créés.
    """
    if document.owner_id != user.id:
        raise PermissionDeniedError("Only the document owner can modify this document.")


def require_document_owner_or_admin(
    user, org_id, document, action: str = "access"
) -> None:
    """
    Vérifie que l'utilisateur est le propriétaire du document OU un ORG_ADMIN.
    Utilisé pour des actions comme publier et désactiver.
    """
    from src.apps.organizations.models import Membership
    from src.common.types import MembershipStatus

    if document.owner_id == user.id:
        return

    if getattr(user, "is_superadmin", False):
        return

    membership = Membership.objects.filter(
        user=user,
        organization_id=org_id,
        status=MembershipStatus.ACTIVE,
        role=Role.ORG_ADMIN,
    ).first()
    if membership:
        return

    raise PermissionDeniedError(
        f"Only the document owner or an org admin can {action} this document."
    )


def require_document_reviewer(user, org_id, document) -> None:
    """
    Vérifie que l'utilisateur peut réviser (approuver/rejeter) le document.
    Prérequis :
      1. L'utilisateur doit être un ORG_ADMIN dans l'organisation.
      2. L'utilisateur NE doit PAS être le propriétaire du document (on ne 
         peut pas réviser son propre travail).
    """
    require_permission(user, org_id, Permission.MANAGE_MEMBERS)

    if document.owner_id == user.id:
        raise PermissionDeniedError("You cannot review your own document.")
