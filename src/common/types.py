# Shared enums (Role, OrgStatus, DocStatus, etc.)
"""
Shared enums used across multiple apps.

These are plain Python StrEnums for use in service logic.
Django model choices are defined on the models themselves.
"""

from enum import StrEnum


class Role(StrEnum):
    ORG_ADMIN = "ORG_ADMIN"
    ORG_MEMBER = "ORG_MEMBER"
    AUDITOR = "AUDITOR"


class OrgStatus(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class MembershipStatus(StrEnum):
    INVITED = "INVITED"
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class CertStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class DocStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    SIGNED = "SIGNED"
    PUBLISHED = "PUBLISHED"
    DEACTIVATED = "DEACTIVATED"


class DocScope(StrEnum):
    """Whether a DID document is organization-level or personal (user-scoped)."""
    ORGANIZATION = "ORGANIZATION"
    PERSONAL = "PERSONAL"


class VerificationPurpose(StrEnum):
    AUTHENTICATION = "authentication"
    ASSERTION_METHOD = "assertionMethod"
    KEY_AGREEMENT = "keyAgreement"
    CAPABILITY_INVOCATION = "capabilityInvocation"
    CAPABILITY_DELEGATION = "capabilityDelegation"


class AuditAction(StrEnum):
    # Organization
    ORG_CREATED = "ORG_CREATED"
    ORG_APPROVED = "ORG_APPROVED"
    ORG_REJECTED = "ORG_REJECTED"
    ORG_SUSPENDED = "ORG_SUSPENDED"
    # Membership
    MEMBER_INVITED = "MEMBER_INVITED"
    MEMBER_ACTIVATED = "MEMBER_ACTIVATED"
    MEMBER_DEACTIVATED = "MEMBER_DEACTIVATED"
    MEMBER_ROLE_CHANGED = "MEMBER_ROLE_CHANGED"
    # Certificates
    CERT_UPLOADED = "CERT_UPLOADED"
    CERT_ROTATED = "CERT_ROTATED"
    CERT_REVOKED = "CERT_REVOKED"
    # DID Documents
    DOC_CREATED = "DOC_CREATED"
    DOC_DRAFT_UPDATED = "DOC_DRAFT_UPDATED"
    DOC_SIGNED = "DOC_SIGNED"
    DOC_PUBLISHED = "DOC_PUBLISHED"
    DOC_DEACTIVATED = "DOC_DEACTIVATED"
    DOC_AUTO_DEACTIVATED = "DOC_AUTO_DEACTIVATED"
    # Auth
    USER_LOGIN = "USER_LOGIN"
    USER_LOGOUT = "USER_LOGOUT"
    OTP_VERIFIED = "OTP_VERIFIED"