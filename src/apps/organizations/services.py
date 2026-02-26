"""
Organization services (write operations).
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


# ── Organization lifecycle ──────────────────────────────────────────────

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

    logger.info("org_created", org_id=str(org.id), slug=org.slug)
    return org

@transaction.atomic
def approve_organization(*, organization: Organization, reviewed_by: User) -> Organization:
    if organization.status != OrgStatus.PENDING_REVIEW:
        raise ValidationError(f"Organization is '{organization.status}', not PENDING_REVIEW.")

    organization.status = OrgStatus.APPROVED
    organization.reviewed_by = reviewed_by
    organization.reviewed_at = timezone.now()
    organization.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])

    logger.info("org_approved", org_id=str(organization.id))
    return organization

@transaction.atomic
def reject_organization(
    *, organization: Organization, reviewed_by: User, reason: str = ""
) -> Organization:
    if organization.status != OrgStatus.PENDING_REVIEW:
        raise ValidationError(f"Organization is '{organization.status}', not PENDING_REVIEW.")

    organization.status = OrgStatus.REJECTED
    organization.reviewed_by = reviewed_by
    organization.reviewed_at = timezone.now()
    organization.rejection_reason = reason
    organization.save(
        update_fields=["status", "reviewed_by", "reviewed_at", "rejection_reason", "updated_at"]
    )

    logger.info("org_rejected", org_id=str(organization.id))
    return organization

@transaction.atomic
def suspend_organization(*, organization: Organization, reviewed_by: User) -> Organization:
    if organization.status != OrgStatus.APPROVED:
        raise ValidationError(f"Can only suspend APPROVED orgs, got '{organization.status}'.")

    organization.status = OrgStatus.SUSPENDED
    organization.reviewed_by = reviewed_by
    organization.reviewed_at = timezone.now()
    organization.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])

    logger.info("org_suspended", org_id=str(organization.id))
    return organization


# ── Membership management ───────────────────────────────────────────────

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

    logger.info("membership_created", user=user.email, org=organization.slug, role=role)
    return membership

@transaction.atomic
def activate_membership(*, membership: Membership) -> Membership:
    if membership.status == MembershipStatus.ACTIVE:
        raise ValidationError("Membership is already active.")

    membership.status = MembershipStatus.ACTIVE
    membership.activated_at = timezone.now()
    membership.save(update_fields=["status", "activated_at", "updated_at"])

    logger.info("membership_activated", user=membership.user.email, org=membership.organization.slug)
    return membership

@transaction.atomic
def invite_member(
    *, organization: Organization, email: str, role: Role, invited_by: User
) -> Membership:
    from src.apps.users.selectors import get_user_by_email
    from src.apps.users.services import create_user

    if role == Role.ORG_ADMIN:
        raise ValidationError("Cannot invite as ORG_ADMIN. Use role change instead.")

    email = email.lower().strip()
    user = get_user_by_email(email=email)

    if user is None:
        import secrets
        user = create_user(
            email=email, full_name="", password=secrets.token_urlsafe(32), is_active=False
        )

    membership = create_membership(
        user=user, organization=organization, role=role,
        status=MembershipStatus.INVITED, invited_by=invited_by,
    )
    return membership

@transaction.atomic
def change_member_role(*, membership: Membership, new_role: Role, changed_by: User) -> Membership:
    old_role = membership.role
    membership.role = new_role
    membership.save(update_fields=["role", "updated_at"])
    logger.info("member_role_changed", old_role=old_role, new_role=new_role)
    return membership

@transaction.atomic
def deactivate_membership(*, membership: Membership, deactivated_by: User) -> Membership:
    membership.status = MembershipStatus.DEACTIVATED
    membership.save(update_fields=["status", "updated_at"])
    logger.info("member_deactivated", user=membership.user.email)
    return membership