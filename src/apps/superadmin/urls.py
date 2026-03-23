from django.urls import path

from src.apps.superadmin import views

app_name = "superadmin"

urlpatterns = [
    path("", views.dashboard_view, name="sa_dashboard"),
    path("organizations/", views.organizations_view, name="sa_organizations"),
    path(
        "organizations/<uuid:org_id>/",
        views.organization_detail_view,
        name="sa_organization_detail",
    ),
    path("users/", views.users_view, name="sa_users"),
    path("audits/", views.audits_view, name="sa_audits"),
    path("did-documents/", views.did_documents_view, name="sa_did_documents"),
    path("certificates/", views.certificates_view, name="sa_certificates"),
]
