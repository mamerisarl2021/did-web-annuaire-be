# DID Documents App — Integration Guide

## Files to deploy

```
src/apps/documents/
├── models.py              (already deployed — no changes)
├── selectors.py           (NEW — read queries)
├── assembler.py           (NEW — builds W3C DID document JSON)
├── services.py            (NEW — all write operations)
├── schemas.py             (NEW — API request/response schemas)
├── apis.py                (NEW — API router with all endpoints)
├── __init__.py            (already exists)
└── apps.py                (already exists)

src/common/
└── permissions.py         (UPDATED — fixed owner_id → created_by_id)

src/urls.py                (UPDATED — mounts doc_router)
```

## 1. Copy files

Copy all files from this delivery to the corresponding paths in your project.

## 2. Update `src/urls.py`

The new `urls.py` adds:
```python
from src.apps.documents.apis import router as doc_router
api.add_router("/org", doc_router)
```

## 3. Run migrations

No new migrations needed — models.py is unchanged.

## 4. Restart the server

```bash
python manage.py runserver
# or restart gunicorn/docker
```

## API Endpoints

All under `/api/v2/org/organizations/{org_id}/documents/`

### Core CRUD
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | JWT | List documents (scoped by role) |
| POST | `/` | JWT | Create new document (DRAFT) |
| GET | `/{doc_id}` | JWT | Document detail |
| PATCH | `/{doc_id}/draft` | JWT | Update draft content |

### Verification Methods
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/{doc_id}/verification-methods` | JWT | Add a cert to document |
| DELETE | `/{doc_id}/verification-methods/{vm_id}` | JWT | Remove a cert from document |

### Review Workflow
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/{doc_id}/submit` | JWT | Submit for review (DRAFT → PENDING_REVIEW) |
| POST | `/{doc_id}/approve` | JWT | Approve (PENDING_REVIEW → APPROVED) — ORG_ADMIN only, not own doc |
| POST | `/{doc_id}/reject` | JWT | Reject (PENDING_REVIEW → REJECTED) — ORG_ADMIN only, not own doc |
| GET | `/pending-review` | JWT | List documents pending review — ORG_ADMIN only |

### Publishing
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/{doc_id}/publish` | JWT | Sign + publish (APPROVED → PUBLISHED) — ORG_ADMIN only |
| POST | `/{doc_id}/deactivate` | JWT | Deactivate (PUBLISHED → DEACTIVATED) — ORG_ADMIN only |

### Public / History
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/{doc_id}/versions` | JWT | List published version history |
| GET | `/{doc_id}/did.json` | None | Public DID resolution (returns published JSON) |

## Scoping Rules

| Role | List | View | Create | Edit | Submit | Review | Publish | Deactivate |
|------|------|------|--------|------|--------|--------|---------|------------|
| ORG_ADMIN | All | All | Own | Own | Own | Others' | Own + Others' | Own + Others' |
| ORG_MEMBER | Own | Own | Own | Own | Own | — | Own | Own |
| AUDITOR | All | All | — | — | — | — | — | — |

## Frontend Files

```
src/apps/documents/
├── static/orgadmin/
│   ├── css/documents.css        (NEW — doc-specific styles)
│   └── js/documents.js          (NEW — DocAPI module + helpers)
├── templates/orgadmin/
│   ├── documents.html           (NEW — list page with create modal)
│   └── document_detail.html     (NEW — detail with full workflow)
└── views.py                     (NEW — template renderers)

src/apps/orgadmin/
├── urls.py                      (UPDATED — adds document routes)
└── templates/orgadmin/
    └── base_orgadmin.html       (UPDATED — active nav links, doc/cert counts)
```

### Frontend Features

**Document List Page** (`/workspace/documents/`)
- Table with label, DID URI, status, VM count, version, creator, last updated
- Status filter tabs (All, Drafts, Pending Review, Published)
- Create modal — enter label, creates a DRAFT, navigates to detail page

**Document Detail Page** (`/workspace/documents/{doc_id}/`)
- Status header with context-aware action buttons
- DID URI display bar
- Review info box (shows rejection reason, approval comment, pending status)
- Verification methods list with Add/Remove (only in editable states)
- Add VM modal — select from user's active certificates, set fragment ID, check relationship types
- Draft/Published JSON viewer with Copy button
- Document info card (status, creator, dates, version count)
- QR code card for published documents with **Download QR Code** button
- Version history list
- Modals: Review (approve/reject with comment), Deactivate (with reason)

## Lifecycle

```
DRAFT ──────→ PENDING_REVIEW ──→ APPROVED ──→ SIGNED ──→ PUBLISHED
                    │                                        │
                    ↓                                        ↓
                REJECTED ──→ re-edit ──→ DRAFT         DEACTIVATED
                                                          │
                                                     (can also edit
                                                      draft_content
                                                      for next version)
```

## SignServer & Universal Registrar

The `sign_and_publish` service calls:
1. **SignServer** — signs the canonical DID document JSON, returns JWS
2. **Universal Registrar** — creates/updates the DID entry

Both have **stub implementations** for development that return placeholder values.
The stubs activate when the configured URLs contain the default Docker service names
(`signserver-node`, `uni-registrar-web`). When you deploy real services with
different URLs, the stubs are bypassed and real HTTP calls are made.

## Key design decisions

1. **Review separation**: Document creator cannot approve/reject their own work.
   This enforces four-eyes principle.

2. **Concurrent editing**: When a PUBLISHED document is edited, changes go to
   `draft_content` while `content` (the live published version) stays untouched.
   The new draft goes through the full review cycle again.

3. **REJECTED → DRAFT**: When a rejected document is edited, it reverts to DRAFT
   status automatically, clearing the review fields.

4. **Verification method validation**: All certificates must be ACTIVE and belong
   to the same organization. Revoked certs are auto-deactivated via the
   `is_active` flag on DocumentVerificationMethod.
