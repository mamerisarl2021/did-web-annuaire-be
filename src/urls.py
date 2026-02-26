"""
Root URL configuration.

- /api/v2/              → Main NinjaExtraAPI (JWT auth, REST endpoints)
- /api/v2/org/          → Org Admin API (scoped to user's orgs)
- /superadmin/api/v2/   → Superadmin API
- /superadmin/          → Superadmin frontend (Django templates)
- /workspace/           → Org admin frontend (Django templates)
- /login/, /register/   → Public frontend (Django templates)
- /admin/
"""

from django.contrib import admin
from django.urls import include, path
from ninja_extra import NinjaExtraAPI
from ninja_jwt.controller import NinjaJWTDefaultController

from src.apps.authentication.apis import router as auth_router
from src.apps.orgadmin.apis import router as orgadmin_router
from src.apps.superadmin.apis import router as superadmin_router
from src.common.exceptions import configure_exception_handlers

# ── Main API ────────────────────────────────────────────────────────────

api = NinjaExtraAPI(
    title="Annuaire DID API",
    version="1.0.1",
    description="DID Directory — decentralized identity management",
    urls_namespace="api",
)

configure_exception_handlers(api)

# ninja_jwt: /api/v2/token/pair, /api/v2/token/refresh, /api/v2/token/verify
api.register_controllers(NinjaJWTDefaultController)

# Custom auth: /api/v2/auth/...
api.add_router("/auth", auth_router)

# Org admin: /api/v2/org/...
api.add_router("/org", orgadmin_router)

# ── Superadmin API ──────────────────────────────────────────────────────

superadmin_api = NinjaExtraAPI(
    title="Annuaire DID Superadmin API",
    version="1.0.1",
    urls_namespace="superadmin_api",
    docs_url="/docs",
)

configure_exception_handlers(superadmin_api)
superadmin_api.add_router("/", superadmin_router)

# ── URL patterns ────────────────────────────────────────────────────────

urlpatterns = [
    # API
    path("api/v2/", api.urls),
    path("superadmin/api/v2/", superadmin_api.urls),

    # Django admin
    path("admin/", admin.site.urls),

    # Superadmin frontend (templates)
    path("superadmin/", include("src.apps.superadmin.urls")),

    # Org admin frontend (templates)
    path("workspace/", include("src.apps.orgadmin.urls")),

    # Public frontend (templates) — must be last (catch-all paths)
    path("", include("src.apps.frontend.urls")),
]