"""
Services d'organisation (opérations d'écriture).

La journalisation d'audit est intégrée dans chaque fonction de mutation via _log_org_audit().
"""

import structlog
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from src.apps.files.models import File
from src.apps.users.models import User
from src.common.exceptions import ConflictError, ValidationError
from src.common.types import MembershipStatus, OrgStatus, Role

from .models import Membership, Organization

logger = structlog.get_logger(__name__)


# ── Cycle de vie de l'organisation ──────────────────────────────────────


@transaction.atomic
def create_organization(
    *,
    name: str,
    slug: str,
    description: str = "",
    type: str = "",
    country: str = "",
    address: str = "",
    email: str = "",
    authorization_document: File | None = None,
    justification_document: File | None = None,
    created_by: User,
) -> Organization:
    slug = slugify(slug)

    if Organization.objects.filter(slug=slug).exists():
        raise ConflictError(f"Organization slug '{slug}' is already taken.")

    if authorization_document is None:
        raise ValidationError("Authorization document is required.")

    org = Organization.objects.create(
        name=name,
        slug=slug,
        description=description,
        type=type,
        country=country,
        address=address,
        email=email,
        authorization_document=authorization_document,
        justification_document=justification_document,
        status=OrgStatus.PENDING_REVIEW,
        created_by=created_by,
    )

    _log_org_audit(
        actor=created_by,
        action="ORG_CREATED",
        organization=org,
        description=f"Organization '{org.name}' (slug: {org.slug}) created.",
        metadata={"slug": org.slug, "type": type, "country": country},
    )
    logger.info("org_created", org_id=str(org.id), slug=org.slug)
    return org


@transaction.atomic
def update_organization(
    *,
    organization: Organization,
    actor: User,
    name: str | None = None,
    type: str | None = None,
    email: str | None = None,
    country: str | None = None,
    address: str | None = None,
    description: str | None = None,
) -> Organization:
    """Mettre à jour les détails de l'organisation (autorisé uniquement pour ORG_ADMIN)."""
    update_fields = ["updated_at"]
    metadata = {}

    if name is not None and name != organization.name:
        organization.name = name
        update_fields.append("name")
        metadata["name"] = name

    if type is not None and type != organization.type:
        organization.type = type
        update_fields.append("type")
        metadata["type"] = type

    if email is not None and email != organization.email:
        organization.email = email
        update_fields.append("email")
        metadata["email"] = email

    if country is not None and country != organization.country:
        organization.country = country
        update_fields.append("country")
        metadata["country"] = country

    if address is not None and address != organization.address:
        organization.address = address
        update_fields.append("address")
        metadata["address"] = address

    if description is not None and description != organization.description:
        organization.description = description
        update_fields.append("description")
        metadata["description"] = description

    if len(update_fields) > 1:
        organization.save(update_fields=update_fields)

        _log_org_audit(
            actor=actor,
            action="ORG_UPDATED",
            organization=organization,
            description=f"Organization '{organization.name}' details updated.",
            metadata=metadata,
        )
        logger.info("org_updated", org_id=str(organization.id), metadata=metadata)

    return organization


@transaction.atomic
def approve_organization(
    *, organization: Organization, reviewed_by: User
) -> Organization:
    if organization.status != OrgStatus.PENDING_REVIEW:
        raise ValidationError(
            f"Organization is '{organization.status}', not PENDING_REVIEW."
        )

    organization.status = OrgStatus.APPROVED
    organization.reviewed_by = reviewed_by
    organization.reviewed_at = timezone.now()
    organization.save(
        update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"]
    )

    invited_admins = Membership.objects.filter(
        organization=organization,
        role=Role.ORG_ADMIN,
        status=MembershipStatus.INVITED
    )
    for membership in invited_admins:
        membership.status = MembershipStatus.PENDING_ACTIVATION
        membership.save(update_fields=["status", "updated_at"])

        _log_membership_audit(
            actor=reviewed_by,
            action="MEMBER_ACTIVATED",  # Pas complètement activé, mais l'état a changé
            membership=membership,
            organization=organization,
            description=f"Membership status for '{membership.user.email}' changed to PENDING_ACTIVATION.",
        )

    _log_org_audit(
        actor=reviewed_by,
        action="ORG_APPROVED",
        organization=organization,
        description=f"Organization '{organization.name}' approved.",
    )
    logger.info("org_approved", org_id=str(organization.id))
    return organization


@transaction.atomic
def reject_organization(
    *, organization: Organization, reviewed_by: User, reason: str = ""
) -> Organization:
    if organization.status != OrgStatus.PENDING_REVIEW:
        raise ValidationError(
            f"Organization is '{organization.status}', not PENDING_REVIEW."
        )

    organization.status = OrgStatus.REJECTED
    organization.reviewed_by = reviewed_by
    organization.reviewed_at = timezone.now()
    organization.rejection_reason = reason
    organization.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "rejection_reason",
            "updated_at",
        ]
    )

    _log_org_audit(
        actor=reviewed_by,
        action="ORG_REJECTED",
        organization=organization,
        description=f"Organization '{organization.name}' rejected.{f' Reason: {reason}' if reason else ''}",
        metadata={"reason": reason},
    )
    logger.info("org_rejected", org_id=str(organization.id))
    return organization


@transaction.atomic
def suspend_organization(
    *, organization: Organization, reviewed_by: User, reason: str = ""
) -> Organization:
    if organization.status != OrgStatus.APPROVED:
        raise ValidationError(
            f"Can only suspend APPROVED orgs, got '{organization.status}'."
        )

    organization.status = OrgStatus.SUSPENDED
    organization.reviewed_by = reviewed_by
    organization.reviewed_at = timezone.now()
    if hasattr(organization, "suspension_reason"):
        organization.suspension_reason = reason
        organization.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "suspension_reason", "updated_at"]
        )
    else:
        # Solution de repli s'il n'y a pas de telle colonne
        organization.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"]
        )

    _log_org_audit(
        actor=reviewed_by,
        action="ORG_SUSPENDED",
        organization=organization,
        description=f"Organization '{organization.name}' suspended. Reason: {reason}" if reason else f"Organization '{organization.name}' suspended.",
        metadata={"reason": reason} if reason else None
    )

    
    from src.apps.emails.tasks import send_organization_suspended_email
    admin_memberships = Membership.objects.filter(organization=organization, role=Role.ORG_ADMIN)
    for admin_membership in admin_memberships:
        send_organization_suspended_email.delay(user_id=str(admin_membership.user.id), org_name=organization.name, reason=reason)

    logger.info("org_suspended", org_id=str(organization.id))
    return organization


@transaction.atomic
def reactivate_organization(
    *, organization: Organization, reviewed_by: User
) -> Organization:
    if organization.status != OrgStatus.SUSPENDED:
        raise ValidationError(
            f"Can only reactivate SUSPENDED orgs, got '{organization.status}'."
        )

    organization.status = OrgStatus.APPROVED
    organization.reviewed_by = reviewed_by
    organization.reviewed_at = timezone.now()
    organization.save(
        update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"]
    )

    _log_org_audit(
        actor=reviewed_by,
        action="ORG_APPROVED",  # ou nous pourrions ajouter ORG_REACTIVATED si nous l'avions
        organization=organization,
        description=f"Organization '{organization.name}' reactivated.",
    )

    # import circulaire avec emails.tasks — intentionnel
    from src.apps.emails.tasks import send_organization_reactivated_email
    admin_memberships = Membership.objects.filter(organization=organization, role=Role.ORG_ADMIN)
    for admin_membership in admin_memberships:
        send_organization_reactivated_email.delay(user_id=str(admin_membership.user.id), org_name=organization.name)

    logger.info("org_reactivated", org_id=str(organization.id))
    return organization


@transaction.atomic
def delete_organization(*, organization: Organization, deleted_by: User) -> None:
    _log_org_audit(
        actor=deleted_by,
        action="ORG_DELETED",
        organization=organization,
        description=f"Organization '{organization.name}' deleted.",
    )
    logger.info("org_deleted", org_id=str(organization.id))
    organization.delete()


# ── Gestion des adhésions ───────────────────────────────────────────────


@transaction.atomic
def create_membership(
    *,
    user: User,
    organization: Organization,
    role: Role,
    status: MembershipStatus = MembershipStatus.INVITED,
    invited_by: User | None = None,
) -> Membership:
    if Membership.objects.filter(user=user, organization=organization).exists():
        raise ConflictError(
            f"User '{user.email}' already has a membership in '{organization.slug}'."
        )

    membership = Membership.objects.create(
        user=user,
        organization=organization,
        role=role,
        status=status,
        invited_by=invited_by,
    )

    _log_membership_audit(
        actor=invited_by or user,
        action="MEMBER_INVITED",
        membership=membership,
        organization=organization,
        description=f"User '{user.email}' invited to '{organization.slug}' as {role}.",
        metadata={"role": role, "invited_by": invited_by.email if invited_by else None},
    )
    logger.info(
        "membership_created",
        user=user.email,
        org=organization.slug,
        role=role,
    )
    return membership


@transaction.atomic
def activate_membership(*, membership: Membership) -> Membership:
    if membership.status == MembershipStatus.ACTIVE:
        raise ValidationError("Membership is already active.")

    membership.status = MembershipStatus.ACTIVE
    membership.activated_at = timezone.now()
    membership.save(update_fields=["status", "activated_at", "updated_at"])

    _log_membership_audit(
        actor=membership.user,
        action="MEMBER_ACTIVATED",
        membership=membership,
        organization=membership.organization,
        description=f"Membership activated for '{membership.user.email}' in '{membership.organization.slug}'.",
    )
    logger.info(
        "membership_activated",
        user=membership.user.email,
        org=membership.organization.slug,
    )
    return membership


@transaction.atomic
def invite_member(
    *, organization: Organization, email: str, role: Role, invited_by: User
) -> Membership:
    # import circulaire avec users.services — intentionnel
    from src.apps.users.selectors import get_user_by_email
    from src.apps.users.services import create_user

    if role == Role.ORG_ADMIN:
        raise ValidationError("Cannot invite as ORG_ADMIN. Use role change instead.")

    email = email.lower().strip()
    user = get_user_by_email(email=email)

    if user is None:
        import secrets

        user = create_user(
            email=email,
            full_name="",
            password=secrets.token_urlsafe(32),
            is_active=False,
        )

    membership = create_membership(
        user=user,
        organization=organization,
        role=role,
        status=MembershipStatus.INVITED,
        invited_by=invited_by,
    )
    return membership


@transaction.atomic
def change_member_role(
    *, membership: Membership, new_role: Role, changed_by: User
) -> Membership:
    """Change le rôle d'un membre. Lève ValidationError si last ORG_ADMIN."""
    old_role = membership.role

    # Garde : empêche de retirer le seul ORG_ADMIN
    if old_role == Role.ORG_ADMIN:
        admin_count = (
            Membership.objects.filter(
                organization_id=membership.organization_id,
                role=Role.ORG_ADMIN,
            )
            .exclude(status=MembershipStatus.DEACTIVATED)
            .count()
        )
        if admin_count <= 1:
            raise ValidationError("Cannot change role of the only organization admin.")

    membership.role = new_role
    membership.save(update_fields=["role", "updated_at"])

    _log_membership_audit(
        actor=changed_by,
        action="MEMBER_ROLE_CHANGED",
        membership=membership,
        organization=membership.organization,
        description=(
            f"Role for '{membership.user.email}' in '{membership.organization.slug}' "
            f"changed from {old_role} to {new_role}."
        ),
        metadata={"old_role": old_role, "new_role": new_role},
    )
    logger.info(
        "member_role_changed",
        user=membership.user.email,
        old_role=old_role,
        new_role=new_role,
    )
    return membership


@transaction.atomic
def deactivate_membership(
    *, membership: Membership, deactivated_by: User
) -> Membership:
    """Désactive un membre. Lève ValidationError si last ORG_ADMIN."""
    # Garde : empêche de désactiver le seul ORG_ADMIN
    if membership.role == Role.ORG_ADMIN:
        admin_count = (
            Membership.objects.filter(
                organization_id=membership.organization_id,
                role=Role.ORG_ADMIN,
            )
            .exclude(status=MembershipStatus.DEACTIVATED)
            .count()
        )
        if admin_count <= 1:
            raise ValidationError("Cannot deactivate the only organization admin.")

    membership.status = MembershipStatus.DEACTIVATED
    membership.save(update_fields=["status", "updated_at"])

    _log_membership_audit(
        actor=deactivated_by,
        action="MEMBER_DEACTIVATED",
        membership=membership,
        organization=membership.organization,
        description=(
            f"Membership for '{membership.user.email}' in "
            f"'{membership.organization.slug}' deactivated."
        ),
        metadata={"deactivated_by": deactivated_by.email},
    )
    logger.info(
        "member_deactivated",
        user=membership.user.email,
        org=membership.organization.slug,
    )
    return membership


@transaction.atomic
def cancel_membership_invitation(*, membership: Membership, canceled_by: User) -> None:
    if membership.status != MembershipStatus.INVITED:
        raise ValidationError("Only INVITED memberships can be canceled.")

    org = membership.organization
    user_email = membership.user.email

    _log_membership_audit(
        actor=canceled_by,
        action="MEMBER_INVITE_CANCELED",
        membership=membership,
        organization=org,
        description=f"Invitation for '{user_email}' was canceled.",
        metadata={"canceled_by": canceled_by.email},
    )

    membership.delete()

    logger.info(
        "membership_invitation_canceled",
        user=user_email,
        org=org.slug,
    )


@transaction.atomic
def reactivate_membership(*, membership: Membership, reactivated_by: User) -> Membership:
    """Réactive un membre désactivé."""
    if membership.status != MembershipStatus.DEACTIVATED:
        raise ValidationError("Only deactivated members can be reactivated.")

    membership.status = MembershipStatus.ACTIVE
    membership.save(update_fields=["status", "updated_at"])

    _log_membership_audit(
        actor=reactivated_by,
        action="MEMBER_ACTIVATED",
        membership=membership,
        organization=membership.organization,
        description=f"Membership for '{membership.user.email}' in '{membership.organization.slug}' reactivated.",
        metadata={"reactivated_by": reactivated_by.email},
    )
    logger.info(
        "membership_reactivated",
        user=membership.user.email,
        org=membership.organization.slug,
    )
    return membership


@transaction.atomic
def update_member_profile(
    *,
    membership: Membership,
    updated_by: User,
    full_name: str | None = None,
    phone: str | None = None,
    functions: str | None = None,
    has_audit_access: bool | None = None,
) -> Membership:
    """
    Met à jour le profil d'un membre (informations personnelles + accès audit).
    Délègue la mise à jour utilisateur à `update_user_profile`.
    """
    # import circulaire avec users.services — intentionnel
    from src.apps.users.services import update_user_profile

    update_user_profile(
        user=membership.user,
        full_name=full_name,
        phone=phone,
        functions=functions,
    )

    if has_audit_access is not None and membership.has_audit_access != has_audit_access:
        membership.has_audit_access = has_audit_access
        membership.save(update_fields=["has_audit_access", "updated_at"])

    _log_membership_audit(
        actor=updated_by,
        action="MEMBER_ROLE_CHANGED",
        membership=membership,
        organization=membership.organization,
        description=f"Member '{membership.user.email}' details updated.",
        metadata={"updated_by": updated_by.email},
    )
    logger.info("member_profile_updated", user=membership.user.email)
    return membership


# ── Assistants d'audit ──────────────────────────────────────────────────


def _log_org_audit(*, actor, action, organization, description, metadata=None):
    """Enregistre une entrée d'audit pour une action au niveau de l'organisation."""
    try:
        from src.apps.audits.services import log_action

        log_action(
            actor=actor,
            action=action,
            resource_type="ORGANIZATION",
            resource_id=organization.id,
            organization=organization,
            description=description,
            metadata=metadata or {},
        )
    except Exception as e:
        logger.warning("audit_log_failed", error=str(e), action=action)


def _log_membership_audit(
    *, actor, action, membership, organization, description, metadata=None
):
    """Enregistre une entrée d'audit pour une action au niveau de l'adhésion."""
    try:
        from src.apps.audits.services import log_action

        log_action(
            actor=actor,
            action=action,
            resource_type="MEMBERSHIP",
            resource_id=membership.id,
            organization=organization,
            description=description,
            metadata=metadata or {},
        )
    except Exception as e:
        logger.warning("audit_log_failed", error=str(e), action=action)