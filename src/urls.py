"""
Root URL configuration.

- /api/v2/          → NinjaExtraAPI (JWT auth, REST endpoints)
- /superadmin/api/v2/ → Superadmin API
- /login/, /register/, etc. → Django Templates + HTMX frontend
- /admin/           → Django admin
"""

from django.contrib import admin
from django.urls import include, path
from ninja_extra import NinjaExtraAPI
from ninja_jwt.controller import NinjaJWTDefaultController

from src.apps.authentication.apis import router as auth_router
from src.common.exceptions import configure_exception_handlers

# ── Main API ────────────────────────────────────────────────────────────

api = NinjaExtraAPI(
    title="Annuaire DID API",
    version="1.0.0",
    description="DID Directory — decentralized identity management",
    urls_namespace="api",
)

configure_exception_handlers(api)

# ninja_jwt: /api/v2/token/pair, /api/v2/token/refresh, /api/v2/token/verify
api.register_controllers(NinjaJWTDefaultController)

# Custom auth: /api/v2/auth/register, /auth/activate/..., /auth/logout, /auth/me, etc.
api.add_router("/auth", auth_router)

# ── Superadmin API ──────────────────────────────────────────────────────

superadmin_api = NinjaExtraAPI(
    title="Annuaire DID Superadmin API",
    version="1.0.0",
    urls_namespace="superadmin_api",
    docs_url="/docs",
)

configure_exception_handlers(superadmin_api)

# ── URL patterns ────────────────────────────────────────────────────────

urlpatterns = [
    # API
    path("api/v2/", api.urls),
    path("superadmin/api/v2/", superadmin_api.urls),

    # Django admin
    path("admin/", admin.site.urls),

    # Frontend (templates + HTMX)
    path("", include("src.apps.frontend.urls")),
]