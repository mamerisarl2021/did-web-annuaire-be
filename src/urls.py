"""
Configuration racine des URL.

- /api/v2/              → API NinjaExtra principale (Auth JWT, points de terminaison REST)
- /api/v2/org/          → API Admin Org (limitée aux organisations de l'utilisateur)
- /api/v2/public/       → API publique (aucune authentification requise)
- /superadmin/api/v2/   → API Superadmin
- /admin/               → Administration Django
"""

from django.contrib import admin
from django.urls import include, path
from ninja_extra import NinjaExtraAPI
from ninja_jwt.controller import NinjaJWTDefaultController

from src.apps.authentication.apis import router as auth_router
from src.apps.certificates.apis import router as cert_router
from src.apps.documents.apis import router as doc_router
from src.apps.documents.public_apis import router as public_search_router
from src.apps.orgadmin.apis import router as orgadmin_router
from src.apps.superadmin.apis import router as superadmin_router
from src.common.exceptions import configure_exception_handlers

# ── API Principale ──────────────────────────────────────────────────────

api = NinjaExtraAPI(
    title="Annuaire DID API",
    version="1.0.1",
    description="DID Directory — decentralized identity management",
    urls_namespace="api",
)

configure_exception_handlers(api)

# ninja_jwt: /api/v2/token/pair, /api/v2/token/refresh, /api/v2/token/verify
api.register_controllers(NinjaJWTDefaultController)

# Auth personnalisée : /api/v2/auth/...
api.add_router("/auth", auth_router)

# Admin org : /api/v2/org/...
api.add_router("/org", orgadmin_router)

# Certificats : /api/v2/org/organizations/{org_id}/certificates/...
api.add_router("/org", cert_router)

# Documents : /api/v2/org/organizations/{org_id}/documents/...
api.add_router("/org", doc_router)

# Recherche publique (sans auth) : /api/v2/public/search/...
api.add_router("/public", public_search_router)

# ── API Superadmin ──────────────────────────────────────────────────────

superadmin_api = NinjaExtraAPI(
    title="Annuaire DID Superadmin API",
    version="1.0.1",
    urls_namespace="superadmin_api",
    docs_url="/docs",
)

configure_exception_handlers(superadmin_api)
superadmin_api.add_router("/", superadmin_router)

# ── Modèles d'URL ───────────────────────────────────────────────────────

urlpatterns = [
    # API
    path("api/v2/", api.urls),
    path("superadmin/api/v2/", superadmin_api.urls),
    # Administration Django
    path("admin/", admin.site.urls),
]
