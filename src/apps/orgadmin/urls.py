"""
Org admin workspace URL configuration.

These are the frontend (template) routes under /workspace/.
"""

from django.urls import path

from src.apps.orgadmin.views import dashboard_view, members_view, settings_view
from src.apps.certificates.views import certificates_view, certificate_detail_view

app_name = "orgadmin"

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("members/", members_view, name="members"),
    path("settings/", settings_view, name="settings"),
    path("certificates/", certificates_view, name="certificates"),
    path("certificates/<uuid:cert_id>/", certificate_detail_view, name="certificate_detail"),
]