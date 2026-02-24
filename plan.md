# DID Directory — Backend Design Document (Final)

> All open questions resolved. This is the reference for implementation.

---

## 1. System Overview

A multi-tenant platform where **organizations** manage **DID documents** (`did:web`) backed by **externally-issued X.509 certificates**. Documents go through a **draft → sign → publish** lifecycle, with platform-level signing via Keyfactor SignServer before a document becomes publicly resolvable.

---

## 2. Decisions Log

| Decision | Choice |
|---|---|
| Auth mechanism | httpOnly cookies (session-based, no JWT in headers) |
| Settings / env | `pydantic_settings` (`BaseSettings`) |
| API framework | django-ninja |
| Architecture | Hacksoft styleguide (services / selectors) |
| Editing published docs | Concurrent draft — published version stays live while next version is drafted |
| DID URI structure | `did:web:host:{org_slug}:{label}` (no user in path) |
| Certificate versioning | Rotation with history — user replaces cert, old version preserved |
| Key revocation effect | Auto-deactivate all published documents referencing the cert |
| AUDITOR role | Standalone read-only role (not layered on ORG_MEMBER) |
| Multi-org | Yes — user can belong to multiple orgs with different roles |
| Cert parsing | Sync call to Java/Bouncy Castle microservice (5s timeout) |
| DID registration | Via Universal Registrar (standards-compliant route) |
| Document signing | SignServer signs with platform key (Data Integrity Proof) |
| Platform DID bootstrap | Management command (`python manage.py bootstrap_platform_did`) |
| Proof format | Data Integrity Proof embedded in DID document |
| Superadmin creation | Management command (`python manage.py createsuperadmin`) |

---

## 3. External Services

| Service | Container name | Internal URL | Purpose |
|---|---|---|---|
| Universal Registrar | `uni-registrar-web` | `http://uni-registrar-web:9080` | Create / update / deactivate DIDs |
| Universal Resolver | `uni-resolver-web` | `http://uni-resolver-web:8080` | Public DID resolution (via nginx) |
| SignServer CE | `signserver-node` | `http://signserver-node:8080` | Sign DID documents with platform key |
| Java Cert Service | `cert-service` | `http://cert-service:8080` | Parse certs (Bouncy Castle), extract JWK |
| Redis | `annuaire-redis` | `redis://annuaire-redis:6379` | Celery broker + result backend + cache |
| PostgreSQL | `annuaire-db` | `postgresql://annuaire-db:5432/annuaire_did` | Primary database |

---

## 4. Django Project Structure

```
src/
├── config/
│   ├── settings.py             # Django settings (reads from env via pydantic)
│   ├── env.py                  # pydantic_settings BaseSettings definition
│   ├── urls.py                 # Root URL config
│   ├── api.py                  # Root django-ninja NinjaAPI instance
│   ├── celery.py               # Celery app
│   └── wsgi.py / asgi.py
│
├── apps/
│   ├── authentication/         # Login, logout, session, OTP/QR activation
│   │   ├── models.py           # (empty — uses User from users app)
│   │   ├── services.py         # login_user, logout_user, setup_otp, verify_otp
│   │   ├── apis.py             # /api/auth/...
│   │   ├── schemas.py          # ninja Schema classes (request/response)
│   │   ├── tasks.py            # Send activation emails
│   │   └── cookies.py          # httpOnly cookie helpers
│   │
│   ├── users/
│   │   ├── models.py           # User (custom AbstractBaseUser)
│   │   ├── services.py         # create_user, activate_account
│   │   ├── selectors.py        # get_user, get_user_by_email
│   │   ├── apis.py             # /api/users/me  (profile)
│   │   ├── schemas.py
│   │   └── managers.py         # Custom UserManager
│   │
│   ├── organizations/
│   │   ├── models.py           # Organization, Membership
│   │   ├── services.py         # create_org, invite_member, change_role, remove_member
│   │   ├── selectors.py        # get_org, get_members, get_user_orgs
│   │   ├── apis.py             # /api/organizations/...
│   │   ├── schemas.py
│   │   └── tasks.py            # Send invitation emails
│   │
│   ├── certificates/
│   │   ├── models.py           # Certificate, CertificateVersion
│   │   ├── services.py         # upload_cert, rotate_cert, revoke_cert
│   │   ├── selectors.py        # get_cert, get_org_certs, get_cert_versions
│   │   ├── apis.py             # /api/organizations/{org_id}/certificates/...
│   │   ├── schemas.py
│   │   └── tasks.py            # Async cert revocation cascade
│   │
│   ├── documents/
│   │   ├── models.py           # DIDDocument, DIDDocumentVersion, DocumentVerificationMethod
│   │   ├── services.py         # create_doc, update_draft, publish_doc, deactivate_doc
│   │   ├── selectors.py        # get_doc, get_org_docs, get_doc_versions
│   │   ├── apis.py             # /api/organizations/{org_id}/documents/...
│   │   ├── schemas.py
│   │   ├── tasks.py            # Async signing + registrar calls
│   │   └── assembler.py        # Builds W3C DID document JSON from model data
│   │
│   ├── audits/
│   │   ├── models.py           # AuditLog
│   │   ├── services.py         # log_action (called by other services)
│   │   ├── selectors.py        # get_org_audits, get_platform_audits
│   │   ├── apis.py             # /api/organizations/{org_id}/audits/
│   │   └── schemas.py
│   │
│   └── superadmin/
│       ├── services.py         # approve_org, reject_org, suspend_org
│       ├── selectors.py        # pending_orgs, all_audits, platform_stats
│       ├── apis.py             # /superadmin/api/...
│       └── schemas.py
│
├── integrations/               # HTTP clients for external services
│   ├── registrar.py            # Universal Registrar client
│   ├── signserver.py           # SignServer client
│   └── cert_service.py         # Java Cert Service client
│
├── common/
│   ├── permissions.py          # RBAC permission dependencies for ninja
│   ├── pagination.py           # Cursor/offset pagination
│   ├── types.py                # Shared enums (Role, OrgStatus, DocStatus, etc.)
│   ├── exceptions.py           # Application exception classes
│   └── middleware.py           # Auth middleware (reads httpOnly cookie → sets request.user)
│
├── management/
│   └── commands/
│       ├── createsuperadmin.py
│       └── bootstrap_platform_did.py
│
└── tasks.py                    # Celery app import alias
```

---

## 5. Environment Configuration

```python
# src/config/env.py

from pydantic_settings import BaseSettings
from pydantic import Field


class AppSettings(BaseSettings):
    # ── Django ──────────────────────────────────────────────
    SECRET_KEY: str
    DEBUG: bool = False
    ALLOWED_HOSTS: list[str] = ["annuairedid-be.qcdigitalhub.com", "localhost"]

    # ── Database ────────────────────────────────────────────
    DATABASE_URL: str = "postgresql://annuaire:changeme@annuaire-db:5432/annuaire_did"

    # ── Redis ───────────────────────────────────────────────
    REDIS_PASSWORD: str = "changeme_redis"
    CELERY_BROKER_URL: str = "redis://:changeme_redis@annuaire-redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://:changeme_redis@annuaire-redis:6379/1"
    CACHE_REDIS_URL: str = "redis://:changeme_redis@annuaire-redis:6379/2"

    # ── Session (httpOnly cookie) ───────────────────────────
    SESSION_COOKIE_NAME: str = "annuaire_session"
    SESSION_COOKIE_AGE: int = 86400  # 24 hours
    SESSION_COOKIE_SECURE: bool = True
    SESSION_COOKIE_DOMAIN: str = ".qcdigitalhub.com"
    CSRF_COOKIE_SECURE: bool = True

    # ── External services ───────────────────────────────────
    UNIVERSAL_REGISTRAR_URL: str = "http://uni-registrar-web:9080"
    SIGNSERVER_URL: str = "http://signserver-node:8080/signserver/process"
    SIGNSERVER_WORKER_NAME: str = "DIDDocumentSigner"
    CERT_SERVICE_URL: str = "http://cert-service:8080"
    CERT_SERVICE_TIMEOUT: int = 5  # seconds

    # ── Platform ────────────────────────────────────────────
    PLATFORM_DOMAIN: str = "annuairedid-be.qcdigitalhub.com"
    PLATFORM_DID: str = "did:web:annuairedid-be.qcdigitalhub.com"

    model_config = {"env_file": ".env.backend", "env_file_encoding": "utf-8"}


settings = AppSettings()
```

---

## 6. Authentication (httpOnly Cookies)

No JWT. The backend uses Django's session framework with cookies marked `httpOnly`, `Secure`, and `SameSite=Lax`.

### Flow

```
POST /api/auth/login
  body: { email, password }
  →  Validates credentials
  →  Creates Django session
  →  Sets httpOnly cookie: annuaire_session=<session_key>
  →  Returns: { user, organizations[] }

Every subsequent request:
  Browser auto-sends the cookie
  →  Django SessionMiddleware reads it
  →  request.user is populated

POST /api/auth/logout
  →  Destroys session
  →  Clears cookie
```

### Django settings for sessions

```python
# In settings.py (populated from pydantic_settings)

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"  # Redis
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = True       # HTTPS only
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_NAME = "annuaire_session"
SESSION_COOKIE_AGE = 86400         # 24 hours
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
```

### CSRF handling

Since we use cookies, CSRF protection is required. Django-ninja endpoints that mutate state need CSRF tokens. Two options:

- **Double-submit cookie**: The CSRF token is also in a cookie. The frontend reads it from the cookie and sends it in `X-CSRFToken` header.
- **Session-bound**: Token stored in session. Frontend gets it from a dedicated endpoint.

**Recommendation**: Double-submit cookie pattern. It's what Django does natively.

---

## 7. RBAC Model

### Roles

| Role | Scope | Can do |
|---|---|---|
| `SUPERADMIN` | Platform | Approve/reject orgs, view all audits, manage platform. Flag on User model. |
| `ORG_ADMIN` | Per-org | All DID/cert ops, invite/remove members, assign roles, view org audits. |
| `ORG_MEMBER` | Per-org | Create/edit/publish DID docs, upload/rotate/revoke certs. |
| `AUDITOR` | Per-org | Read-only: view docs, certs, audit logs. No mutations. |

### Permission matrix

| Action | ORG_ADMIN | ORG_MEMBER | AUDITOR |
|---|---|---|---|
| View documents | ✓ | ✓ | ✓ |
| Create document | ✓ | ✓ | ✗ |
| Edit draft | ✓ | ✓ | ✗ |
| Publish document | ✓ | ✓ | ✗ |
| Deactivate document | ✓ | ✓ | ✗ |
| Upload certificate | ✓ | ✓ | ✗ |
| Rotate certificate | ✓ | ✓ | ✗ |
| Revoke certificate | ✓ | ✗ | ✗ |
| Invite members | ✓ | ✗ | ✗ |
| Remove members | ✓ | ✗ | ✗ |
| Change member roles | ✓ | ✗ | ✗ |
| View audit logs | ✓ | ✗ | ✓ |

### Implementation

```python
# src/common/permissions.py

from enum import StrEnum
from functools import wraps
from django.http import HttpRequest
from apps.organizations.selectors import get_active_membership


class Role(StrEnum):
    ORG_ADMIN = "ORG_ADMIN"
    ORG_MEMBER = "ORG_MEMBER"
    AUDITOR = "AUDITOR"


class Permission(StrEnum):
    VIEW_DOCUMENTS = "view_documents"
    MUTATE_DOCUMENTS = "mutate_documents"
    VIEW_CERTIFICATES = "view_certificates"
    MUTATE_CERTIFICATES = "mutate_certificates"
    REVOKE_CERTIFICATES = "revoke_certificates"
    MANAGE_MEMBERS = "manage_members"
    VIEW_AUDITS = "view_audits"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ORG_ADMIN: {p for p in Permission},  # all permissions
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
```

---

## 8. Data Model

### 8.1 User

```python
class User(AbstractBaseUser):
    id              = UUIDField(primary_key=True, default=uuid4)
    email           = EmailField(unique=True)  # login identifier
    full_name       = CharField(max_length=255)
    is_active       = BooleanField(default=False)  # activated via OTP
    is_superadmin   = BooleanField(default=False)  # separate from org roles
    activation_method = CharField(choices=["OTP", "QR"], default="OTP")
    otp_secret      = CharField(max_length=64, blank=True)  # encrypted TOTP secret
    account_activated_at = DateTimeField(null=True, blank=True)
    created_at      = DateTimeField(auto_now_add=True)
    updated_at      = DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
```

### 8.2 Organization

```python
class OrgStatus(models.TextChoices):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED       = "APPROVED"
    REJECTED       = "REJECTED"
    SUSPENDED      = "SUSPENDED"


class Organization(models.Model):
    id            = UUIDField(primary_key=True, default=uuid4)
    name          = CharField(max_length=255)
    slug          = SlugField(unique=True)  # URL-safe, used in DID URI path
    description   = TextField(blank=True)
    status        = CharField(choices=OrgStatus.choices, default=OrgStatus.PENDING_REVIEW)
    created_by    = ForeignKey(User, on_delete=PROTECT, related_name="founded_orgs")
    reviewed_by   = ForeignKey(User, on_delete=SET_NULL, null=True, blank=True)
    reviewed_at   = DateTimeField(null=True, blank=True)
    rejection_reason = TextField(blank=True)
    created_at    = DateTimeField(auto_now_add=True)
    updated_at    = DateTimeField(auto_now=True)
```

### 8.3 Membership

```python
class MembershipStatus(models.TextChoices):
    INVITED              = "INVITED"
    PENDING_ACTIVATION   = "PENDING_ACTIVATION"
    ACTIVE               = "ACTIVE"
    DEACTIVATED          = "DEACTIVATED"


class Membership(models.Model):
    id               = UUIDField(primary_key=True, default=uuid4)
    user             = ForeignKey(User, on_delete=CASCADE, related_name="memberships")
    organization     = ForeignKey(Organization, on_delete=CASCADE, related_name="memberships")
    role             = CharField(choices=Role.choices, max_length=20)
    status           = CharField(choices=MembershipStatus.choices, default=MembershipStatus.INVITED)
    invited_by       = ForeignKey(User, on_delete=SET_NULL, null=True, blank=True)
    invitation_token = UUIDField(default=uuid4, unique=True)
    activated_at     = DateTimeField(null=True, blank=True)
    created_at       = DateTimeField(auto_now_add=True)
    updated_at       = DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "organization")]
```

### 8.4 Certificate (with rotation history)

```python
class CertStatus(models.TextChoices):
    ACTIVE  = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Certificate(models.Model):
    """
    Represents a certificate 'slot'. When a user rotates (renews) a cert,
    the current data moves into CertificateVersion as history, and the
    new cert data overwrites the fields here. current_version increments.
    """
    id                  = UUIDField(primary_key=True, default=uuid4)
    organization        = ForeignKey(Organization, on_delete=CASCADE, related_name="certificates")
    uploaded_by         = ForeignKey(User, on_delete=PROTECT)
    label               = CharField(max_length=255)  # user-given name
    fingerprint_sha256  = CharField(max_length=64)    # hex, unique within org
    subject_dn          = CharField(max_length=500)
    issuer_dn           = CharField(max_length=500)
    serial_number       = CharField(max_length=100)
    not_before          = DateTimeField()
    not_after           = DateTimeField()
    raw_pem             = TextField()                 # current PEM
    public_key_jwk      = JSONField()                 # current JWK (from Java service)
    key_type            = CharField(max_length=20)    # RSA, EC, Ed25519, Ed448, ...
    status              = CharField(choices=CertStatus.choices, default=CertStatus.ACTIVE)
    current_version     = PositiveIntegerField(default=1)
    revoked_at          = DateTimeField(null=True, blank=True)
    revoked_by          = ForeignKey(User, on_delete=SET_NULL, null=True, blank=True,
                                     related_name="revoked_certs")
    revocation_reason   = TextField(blank=True)
    created_at          = DateTimeField(auto_now_add=True)
    updated_at          = DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("organization", "fingerprint_sha256")]


class CertificateVersion(models.Model):
    """
    Archived version of a certificate after rotation.
    Each row is a snapshot of what the Certificate looked like before
    the user replaced it with a new cert.
    """
    id                  = UUIDField(primary_key=True, default=uuid4)
    certificate         = ForeignKey(Certificate, on_delete=CASCADE, related_name="versions")
    version_number      = PositiveIntegerField()
    fingerprint_sha256  = CharField(max_length=64)
    subject_dn          = CharField(max_length=500)
    issuer_dn           = CharField(max_length=500)
    serial_number       = CharField(max_length=100)
    not_before          = DateTimeField()
    not_after           = DateTimeField()
    raw_pem             = TextField()
    public_key_jwk      = JSONField()
    key_type            = CharField(max_length=20)
    change_summary      = CharField(max_length=500)  # e.g. "Rotated: renewed cert from DigiCert"
    created_by          = ForeignKey(User, on_delete=PROTECT)
    created_at          = DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("certificate", "version_number")]
        ordering = ["-version_number"]
```

### 8.5 DID Document (with concurrent draft)

```python
class DocStatus(models.TextChoices):
    DRAFT             = "DRAFT"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    SIGNED            = "SIGNED"
    PUBLISHED         = "PUBLISHED"
    DEACTIVATED       = "DEACTIVATED"


class DIDDocument(models.Model):
    """
    Represents a single DID identity for an organization.

    When published, a 'draft_content' field allows editing the next version
    while the current 'content' remains live and publicly resolvable.
    """
    id                = UUIDField(primary_key=True, default=uuid4)
    organization      = ForeignKey(Organization, on_delete=CASCADE, related_name="documents")
    created_by        = ForeignKey(User, on_delete=PROTECT, related_name="created_documents")
    label             = SlugField(max_length=100)  # the {label} in the URI
    did_uri           = CharField(max_length=500, unique=True)
    # e.g. "did:web:annuairedid-be.qcdigitalhub.com:acme-corp:corporate-auth"

    # Live content (what's publicly served as did.json when published)
    content           = JSONField(default=dict)

    # Draft content (next version being edited — only exists after first publish)
    # While status=DRAFT (never published), content IS the draft.
    # While status=PUBLISHED, draft_content holds the in-progress next version.
    draft_content     = JSONField(null=True, blank=True)

    status            = CharField(choices=DocStatus.choices, default=DocStatus.DRAFT)
    current_version   = PositiveIntegerField(default=1)
    published_at      = DateTimeField(null=True, blank=True)
    deactivated_at    = DateTimeField(null=True, blank=True)
    deactivated_reason = TextField(blank=True)
    created_at        = DateTimeField(auto_now_add=True)
    updated_at        = DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("organization", "label")]


class DIDDocumentVersion(models.Model):
    """
    Immutable snapshot of a DID document at a point in time.
    Created when a document is published (archives the published content).
    """
    id              = UUIDField(primary_key=True, default=uuid4)
    document        = ForeignKey(DIDDocument, on_delete=CASCADE, related_name="versions")
    version_number  = PositiveIntegerField()
    content         = JSONField()         # full DID doc JSON at this version
    signature       = TextField(blank=True)  # JWS from SignServer
    signed_at       = DateTimeField(null=True, blank=True)
    published_at    = DateTimeField(null=True, blank=True)
    created_by      = ForeignKey(User, on_delete=PROTECT)
    created_at      = DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("document", "version_number")]
        ordering = ["-version_number"]


class VerificationPurpose(models.TextChoices):
    AUTHENTICATION          = "authentication"
    ASSERTION_METHOD        = "assertionMethod"
    KEY_AGREEMENT           = "keyAgreement"
    CAPABILITY_INVOCATION   = "capabilityInvocation"
    CAPABILITY_DELEGATION   = "capabilityDelegation"


class DocumentVerificationMethod(models.Model):
    """
    Links a DID document to a certificate's public key.
    Maps to the 'verificationMethod' array in the DID document.
    """
    id            = UUIDField(primary_key=True, default=uuid4)
    document      = ForeignKey(DIDDocument, on_delete=CASCADE, related_name="verification_methods")
    certificate   = ForeignKey(Certificate, on_delete=PROTECT, related_name="verification_methods")
    key_id        = CharField(max_length=100)  # fragment, e.g. "#key-1"
    method_type   = CharField(max_length=50, default="JsonWebKey2020")
    purpose       = CharField(choices=VerificationPurpose.choices, max_length=30)
    created_at    = DateTimeField(auto_now_add=True)
    updated_at    = DateTimeField(auto_now=True)
```

### 8.6 Audit Log

```python
class AuditAction(models.TextChoices):
    # Organization
    ORG_CREATED           = "ORG_CREATED"
    ORG_APPROVED          = "ORG_APPROVED"
    ORG_REJECTED          = "ORG_REJECTED"
    ORG_SUSPENDED         = "ORG_SUSPENDED"
    # Membership
    MEMBER_INVITED        = "MEMBER_INVITED"
    MEMBER_ACTIVATED      = "MEMBER_ACTIVATED"
    MEMBER_DEACTIVATED    = "MEMBER_DEACTIVATED"
    MEMBER_ROLE_CHANGED   = "MEMBER_ROLE_CHANGED"
    # Certificates
    CERT_UPLOADED         = "CERT_UPLOADED"
    CERT_ROTATED          = "CERT_ROTATED"
    CERT_REVOKED          = "CERT_REVOKED"
    # DID Documents
    DOC_CREATED           = "DOC_CREATED"
    DOC_DRAFT_UPDATED     = "DOC_DRAFT_UPDATED"
    DOC_SIGNED            = "DOC_SIGNED"
    DOC_PUBLISHED         = "DOC_PUBLISHED"
    DOC_DEACTIVATED       = "DOC_DEACTIVATED"
    DOC_AUTO_DEACTIVATED  = "DOC_AUTO_DEACTIVATED"
    # Auth
    USER_LOGIN            = "USER_LOGIN"
    USER_LOGOUT           = "USER_LOGOUT"
    OTP_VERIFIED          = "OTP_VERIFIED"


class AuditLog(models.Model):
    id            = UUIDField(primary_key=True, default=uuid4)
    organization  = ForeignKey(Organization, on_delete=CASCADE, null=True, blank=True,
                               related_name="audit_logs")
    actor         = ForeignKey(User, on_delete=SET_NULL, null=True)
    action        = CharField(choices=AuditAction.choices, max_length=30)
    target_type   = CharField(max_length=50)        # e.g. "DIDDocument", "Certificate"
    target_id     = UUIDField(null=True, blank=True)
    metadata      = JSONField(default=dict)          # action-specific details
    ip_address    = GenericIPAddressField(null=True, blank=True)
    created_at    = DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["action"]),
        ]
```

---

## 9. Core Flows

### 9.1 Organization Registration

```
POST /api/auth/register
body: { email, full_name, password, org_name, org_slug, org_description }

→ services.users.create_user(email, full_name, password)
    → User(is_active=False)
→ services.organizations.create_organization(name, slug, description, created_by=user)
    → Organization(status=PENDING_REVIEW)
→ services.organizations.create_membership(user, org, role=ORG_ADMIN, status=INVITED)
→ services.audits.log(ORG_CREATED, org, user, target=org)
→ Response: 201 { message: "Registration submitted for review" }
```

### 9.2 Superadmin Approves → Activation Flow

```
POST /superadmin/api/organizations/{org_id}/approve
→ Org.status = APPROVED
→ Celery task: send activation email to ORG_ADMIN
→ services.audits.log(ORG_APPROVED)

GET /api/auth/activate/{invitation_token}
→ Returns OTP secret + QR code URI (for authenticator app)
→ Membership.status = PENDING_ACTIVATION

POST /api/auth/activate/{invitation_token}/verify
body: { otp_code }
→ Verify TOTP(otp_secret, otp_code)
→ User.is_active = True
→ User.account_activated_at = now()
→ Membership.status = ACTIVE
→ Set httpOnly session cookie (user is now logged in)
→ services.audits.log(MEMBER_ACTIVATED)
```

### 9.3 Member Invitation

```
POST /api/organizations/{org_id}/members/invite
body: { email, role: ORG_MEMBER | AUDITOR }
Requires: ORG_ADMIN

→ services.organizations.invite_member(org, email, role, invited_by)
    → If user doesn't exist: create User(is_active=False)
    → If user exists but not in this org: create Membership
    → If user already in this org: 409 Conflict
    → Membership(status=INVITED, invitation_token=uuid4())
→ Celery task: send invitation email with activation link
→ services.audits.log(MEMBER_INVITED)
→ Invited user activates via same OTP/QR flow (9.2)
```

### 9.4 Certificate Upload

```
POST /api/organizations/{org_id}/certificates/upload
body: { label, cert_file (PEM) }
Requires: ORG_ADMIN or ORG_MEMBER

→ services.certificates.upload_certificate(org, user, label, pem_data)
    1. Call Java Cert Service: POST http://cert-service:8080/parse
       body: { pem: "..." }
       ← Response: { jwk, subject_dn, issuer_dn, serial, not_before, not_after, key_type }
       (5s timeout — if fails, return 502 to user)
    2. Check fingerprint uniqueness within org
    3. Create Certificate(
         organization=org, uploaded_by=user, label=label,
         raw_pem=pem, public_key_jwk=jwk, status=ACTIVE,
         current_version=1, ...parsed fields
       )
    4. Create CertificateVersion(version_number=1, ...)  # initial version
→ services.audits.log(CERT_UPLOADED)
→ Response: 201 { certificate details + JWK }
```

### 9.5 Certificate Rotation

```
POST /api/organizations/{org_id}/certificates/{cert_id}/rotate
body: { cert_file (PEM), change_summary }
Requires: ORG_ADMIN or ORG_MEMBER

→ services.certificates.rotate_certificate(cert, user, new_pem, summary)
    1. Archive current cert data into CertificateVersion(
         version_number=cert.current_version,
         fingerprint=cert.fingerprint, pem=cert.raw_pem, jwk=cert.public_key_jwk, ...
       )
    2. Parse new cert via Java service
    3. Overwrite Certificate fields with new cert data
    4. cert.current_version += 1
    5. Update any DRAFT documents referencing this cert:
       → Re-assemble their content with the new JWK
→ services.audits.log(CERT_ROTATED)
→ Response: 200 { updated certificate }
```

### 9.6 Certificate Revocation → Auto-Deactivation

```
POST /api/organizations/{org_id}/certificates/{cert_id}/revoke
body: { reason }
Requires: ORG_ADMIN only

→ services.certificates.revoke_certificate(cert, user, reason)
    1. cert.status = REVOKED, revoked_at = now(), revoked_by = user
    2. services.audits.log(CERT_REVOKED)
    3. Trigger Celery task: cascade_revocation(cert_id)
         → Find all DIDDocuments linked via DocumentVerificationMethod
         → For each PUBLISHED document:
             → Call Universal Registrar: POST /1.0/deactivate
             → doc.status = DEACTIVATED
             → doc.deactivated_at = now()
             → doc.deactivated_reason = f"Auto: cert {cert.label} revoked"
             → services.audits.log(DOC_AUTO_DEACTIVATED)
         → For each DRAFT document:
             → Remove the DocumentVerificationMethod linking to revoked cert
             → Re-assemble draft content without that key
```

### 9.7 DID Document Creation (Draft)

```
POST /api/organizations/{org_id}/documents
body: {
  label: "corporate-auth",
  verification_methods: [
    { certificate_id: "...", key_id: "#key-1", purpose: "authentication" },
    { certificate_id: "...", key_id: "#key-2", purpose: "assertionMethod" }
  ],
  service_endpoints: [ ... ]    # optional
}
Requires: ORG_ADMIN or ORG_MEMBER

→ services.documents.create_document(org, user, label, verification_methods, services)
    1. Validate: all certs belong to this org and are ACTIVE
    2. Validate: label is unique within org (URL-safe slug)
    3. Construct DID URI: did:web:{PLATFORM_DOMAIN}:{org.slug}:{label}
    4. Build DID document JSON (via assembler.py):
       → @context, id, verificationMethod[], authentication[], ...
    5. Create DIDDocument(
         organization=org, created_by=user, label=label,
         did_uri=uri, content=did_doc_json, status=DRAFT,
         current_version=1
       )
    6. Create DocumentVerificationMethod records
    7. Create DIDDocumentVersion(version_number=1, content=did_doc_json)
→ services.audits.log(DOC_CREATED)
→ Response: 201 { document with content }
```

### 9.8 Edit Draft (concurrent with published)

```
PATCH /api/organizations/{org_id}/documents/{doc_id}/draft
body: { verification_methods?, service_endpoints?, ... }
Requires: ORG_ADMIN or ORG_MEMBER

If doc.status == DRAFT (never published):
    → Edit content directly
    → services.audits.log(DOC_DRAFT_UPDATED)

If doc.status == PUBLISHED:
    → Edit draft_content (leave content untouched — it's the live version)
    → If draft_content is null, copy content → draft_content first
    → Apply changes to draft_content
    → services.audits.log(DOC_DRAFT_UPDATED)

→ Response: 200 { document with draft }
```

### 9.9 Publish Document

```
POST /api/organizations/{org_id}/documents/{doc_id}/publish
Requires: ORG_ADMIN or ORG_MEMBER

→ services.documents.publish_document(doc, user)
    1. Determine content to publish:
       → If DRAFT (never published): use content
       → If PUBLISHED (editing next version): use draft_content
    2. Validate: all referenced certs still ACTIVE
    3. doc.status = PENDING_SIGNATURE
    4. Canonicalize the DID document
    5. Call SignServer:
       POST http://signserver-node:8080/signserver/process
       { workerName: "DIDDocumentSigner", data: <canonical bytes> }
       ← JWS signature
    6. Attach proof block to the document
    7. doc.status = SIGNED
    8. services.audits.log(DOC_SIGNED)
    9. Call Universal Registrar:
       If first publish: POST /1.0/create { method: "web", didDocument: {...} }
       If update:        POST /1.0/update { did: "...", didDocument: {...} }
       ← Registrar driver writes did.json to shared volume
    10. Archive previous version:
        → Create DIDDocumentVersion(version_number=prev, content=prev_content, ...)
    11. doc.content = signed document
        doc.draft_content = null
        doc.status = PUBLISHED
        doc.published_at = now()
        doc.current_version += 1
    12. Create DIDDocumentVersion(version_number=current, content=signed_doc,
          signature=jws, signed_at=now, published_at=now)
    13. services.audits.log(DOC_PUBLISHED)

→ Response: 200 { published document }
```

### 9.10 Deactivate Document (manual)

```
POST /api/organizations/{org_id}/documents/{doc_id}/deactivate
body: { reason }
Requires: ORG_ADMIN or ORG_MEMBER

→ services.documents.deactivate_document(doc, user, reason)
    1. Call Universal Registrar: POST /1.0/deactivate
    2. doc.status = DEACTIVATED
    3. doc.deactivated_at = now()
    4. doc.deactivated_reason = reason
→ services.audits.log(DOC_DEACTIVATED)
```

---

## 10. DID Document Assembly

```python
# src/apps/documents/assembler.py

def assemble_did_document(
    did_uri: str,
    verification_methods: list[DocumentVerificationMethod],
    service_endpoints: list[dict] | None = None,
) -> dict:
    """
    Builds a W3C DID Core compliant document from model data.
    """
    methods = []
    auth_refs = []
    assertion_refs = []
    key_agreement_refs = []

    for vm in verification_methods:
        method_entry = {
            "id": f"{did_uri}{vm.key_id}",
            "type": vm.method_type,
            "controller": did_uri,
            "publicKeyJwk": vm.certificate.public_key_jwk,
        }
        methods.append(method_entry)

        ref = vm.key_id
        if vm.purpose == "authentication":
            auth_refs.append(ref)
        elif vm.purpose == "assertionMethod":
            assertion_refs.append(ref)
        elif vm.purpose == "keyAgreement":
            key_agreement_refs.append(ref)

    doc = {
        "@context": [
            "https://www.w3.org/ns/did/v1",
            "https://w3id.org/security/suites/jws-2020/v1",
        ],
        "id": did_uri,
        "verificationMethod": methods,
    }

    if auth_refs:
        doc["authentication"] = auth_refs
    if assertion_refs:
        doc["assertionMethod"] = assertion_refs
    if key_agreement_refs:
        doc["keyAgreement"] = key_agreement_refs
    if service_endpoints:
        doc["service"] = service_endpoints

    return doc
```

---

## 11. API Surface

### Public (no auth)

```
POST   /api/auth/register                        Register user + org
POST   /api/auth/login                           Login → sets httpOnly cookie
POST   /api/auth/logout                          Logout → clears cookie
GET    /api/auth/activate/{token}                Get OTP/QR setup
POST   /api/auth/activate/{token}/verify         Verify OTP → activate + login
GET    /api/auth/session                         Check if session is valid (returns user info or 401)
```

### Authenticated — Organizations

```
GET    /api/organizations                        List user's orgs + roles
GET    /api/organizations/{org_id}               Org detail
```

### Authenticated — Members (ORG_ADMIN for mutations)

```
GET    /api/organizations/{org_id}/members
POST   /api/organizations/{org_id}/members/invite
PATCH  /api/organizations/{org_id}/members/{member_id}    Change role
DELETE /api/organizations/{org_id}/members/{member_id}    Deactivate
```

### Authenticated — Certificates

```
GET    /api/organizations/{org_id}/certificates
POST   /api/organizations/{org_id}/certificates/upload
GET    /api/organizations/{org_id}/certificates/{cert_id}
GET    /api/organizations/{org_id}/certificates/{cert_id}/versions
POST   /api/organizations/{org_id}/certificates/{cert_id}/rotate
POST   /api/organizations/{org_id}/certificates/{cert_id}/revoke          ORG_ADMIN only
```

### Authenticated — DID Documents

```
GET    /api/organizations/{org_id}/documents
POST   /api/organizations/{org_id}/documents
GET    /api/organizations/{org_id}/documents/{doc_id}
PATCH  /api/organizations/{org_id}/documents/{doc_id}/draft
POST   /api/organizations/{org_id}/documents/{doc_id}/publish
POST   /api/organizations/{org_id}/documents/{doc_id}/deactivate
GET    /api/organizations/{org_id}/documents/{doc_id}/versions
```

### Authenticated — Audit Logs (ORG_ADMIN + AUDITOR)

```
GET    /api/organizations/{org_id}/audits?action=...&after=...&before=...
```

### Superadmin (requires is_superadmin)

```
GET    /superadmin/api/organizations?status=PENDING_REVIEW
GET    /superadmin/api/organizations/{org_id}
POST   /superadmin/api/organizations/{org_id}/approve
POST   /superadmin/api/organizations/{org_id}/reject
POST   /superadmin/api/organizations/{org_id}/suspend
GET    /superadmin/api/audits?action=...&org_id=...
GET    /superadmin/api/stats
```

---

## 12. Nginx DID Path (updated)

Since the URI is `did:web:host:{org_slug}:{label}`, the path is `/{org_slug}/{label}/did.json`:

```nginx
# Two-segment DID path: /{org_slug}/{label}/did.json
location ~ ^/([a-zA-Z0-9._-]+)/([a-zA-Z0-9._-]+)/did\.json$ {
    root /app/data/dids/.well-known;
    try_files $uri =404;

    default_type application/did+json;
    add_header Access-Control-Allow-Origin  "*" always;
    add_header Cache-Control "public, max-age=300";
    add_header X-DID-Env "PROD";
    limit_except GET HEAD { deny all; }
}
```

---

## 13. Tech Stack

| Layer | Choice |
|---|---|
| Framework | Django 5.x |
| API | django-ninja |
| Architecture | Hacksoft styleguide (services / selectors) |
| Auth | httpOnly session cookies (Django sessions in Redis) |
| Env config | pydantic_settings |
| Task queue | Celery + Redis |
| Cache | Django Redis cache (sessions + general) |
| DB | PostgreSQL 18 |
| Cert parsing | Plain Java + Bouncy Castle (HTTP microservice) |
| DID signing | Keyfactor SignServer CE (platform key) |
| DID registration | DIF Universal Registrar |
| DID resolution | DIF Universal Resolver (public, via nginx) |
| OTP / 2FA | pyotp (TOTP) + qrcode library |