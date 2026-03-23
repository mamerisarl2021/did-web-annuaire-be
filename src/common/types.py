# Énumérations partagées (Role, OrgStatus, DocStatus, etc.)
"""
Énumérations partagées utilisées par plusieurs applications.

Ce sont de simples StrEnums Python pour la logique de service.
Les choix de modèles Django sont définis sur les modèles eux-mêmes.
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



class DocStatus(StrEnum):
    """
    CORRECTION : Synchronisé avec documents/models.py.
    L'ancien enum avait PENDING_SIGNATURE mais le modèle utilise PENDING_REVIEW + APPROVED.
    """

    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SIGNED = "SIGNED"
    PUBLISHED = "PUBLISHED"
    DEACTIVATED = "DEACTIVATED"


class AuditAction(StrEnum):
    # Organisation
    ORG_CREATED = "ORG_CREATED"
    ORG_APPROVED = "ORG_APPROVED"
    ORG_REJECTED = "ORG_REJECTED"
    ORG_SUSPENDED = "ORG_SUSPENDED"
    # Adhésion
    MEMBER_INVITED = "MEMBER_INVITED"
    MEMBER_INVITE_CANCELED = "MEMBER_INVITE_CANCELED"
    MEMBER_ACTIVATED = "MEMBER_ACTIVATED"
    MEMBER_DEACTIVATED = "MEMBER_DEACTIVATED"
    MEMBER_ROLE_CHANGED = "MEMBER_ROLE_CHANGED"
    # Certificats
    CERT_UPLOADED = "CERT_UPLOADED"
    CERT_ROTATED = "CERT_ROTATED"
    CERT_REVOKED = "CERT_REVOKED"
    # Documents DID
    DOC_CREATED = "DOC_CREATED"
    DOC_DRAFT_UPDATED = "DOC_DRAFT_UPDATED"
    DOC_SUBMITTED = "DOC_SUBMITTED"
    DOC_APPROVED = "DOC_APPROVED"
    DOC_REJECTED = "DOC_REJECTED"
    DOC_SIGNED = "DOC_SIGNED"
    DOC_PUBLISHED = "DOC_PUBLISHED"
    DOC_DEACTIVATED = "DOC_DEACTIVATED"
    DOC_AUTO_DEACTIVATED = "DOC_AUTO_DEACTIVATED"
    DOC_VM_ADDED = "DOC_VM_ADDED"
    DOC_VM_REMOVED = "DOC_VM_REMOVED"
    # Résolution / Recherche DID
    DID_RESOLVED = "DID_RESOLVED"
    DID_SEARCHED = "DID_SEARCHED"
    # Authentification
    USER_LOGIN = "USER_LOGIN"
    USER_LOGOUT = "USER_LOGOUT"
    OTP_VERIFIED = "OTP_VERIFIED"
