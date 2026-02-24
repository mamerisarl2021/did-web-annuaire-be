"""
Root URL configuration.

The NinjaAPI instance mounts all app routers.
Superadmin gets a completely separate NinjaAPI instance.
"""

from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI

#from src.common.exceptions import configure_exception_handlers

# ── Main API (org-scoped + auth) ────────────────────────────────────────

api = NinjaAPI(
    title="Annuaire DID API",
    version="1.0.0",
    description="DID Directory — decentralized identity management",
    urls_namespace="api",
    csrf=True,  # Required for httpOnly cookie auth
)

#configure_exception_handlers(api)

# Routers will be added as apps are built:
# from src.apps.authentication.apis import router as auth_router
# from src.apps.organizations.apis import router as orgs_router
# from src.apps.certificates.apis import router as certs_router
# from src.apps.documents.apis import router as docs_router
# from src.apps.audits.apis import router as audits_router
#
# api.add_router("/auth", auth_router, tags=["Authentication"])
# api.add_router("/organizations", orgs_router, tags=["Organizations"])

# ── Superadmin API (separate instance, separate prefix) ─────────────────

superadmin_api = NinjaAPI(
    title="Annuaire DID Superadmin API",
    version="1.0.0",
    urls_namespace="superadmin_api",
    csrf=True,
    docs_url="/docs",
)

#configure_exception_handlers(superadmin_api)

# from src.apps.superadmin.apis import router as superadmin_router
# superadmin_api.add_router("/", superadmin_router, tags=["Superadmin"])

# ── URL patterns ────────────────────────────────────────────────────────

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    #path("superadmin/api/", superadmin_api.urls),
]