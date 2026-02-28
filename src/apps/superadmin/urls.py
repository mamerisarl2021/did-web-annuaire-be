from django.urls import path

from src.apps.superadmin import views

app_name = "superadmin"

urlpatterns = [
    path("", views.dashboard_view, name="sa_dashboard"),
    path("organizations/", views.organizations_view, name="sa_organizations"),
    path("organizations/<uuid:org_id>/", views.organization_detail_view, name="sa_organization_detail"),
]