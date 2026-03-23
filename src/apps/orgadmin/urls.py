"""
Org admin workspace URL configuration.

Frontend (template) routes under /workspace/.
"""

from django.urls import path

from src.apps.certificates.views import certificate_detail_view, certificates_view
from src.apps.documents.views import document_detail_view, documents_view
from src.apps.orgadmin.views import (
    audits_view,
    dashboard_view,
    members_view,
    settings_view,
)

app_name = "orgadmin"

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("members/", members_view, name="members"),
    path("settings/", settings_view, name="settings"),
    path("certificates/", certificates_view, name="certificates"),
    path(
        "certificates/<uuid:cert_id>/",
        certificate_detail_view,
        name="certificate_detail",
    ),
    path("documents/", documents_view, name="documents"),
    path("documents/<uuid:doc_id>/", document_detail_view, name="document_detail"),
    path("audits/", audits_view, name="audits"),
]
