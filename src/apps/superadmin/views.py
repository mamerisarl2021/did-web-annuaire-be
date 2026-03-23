"""
Superadmin views.

Thin template renderers. All data is fetched client-side via JWT API.
"""

from django.shortcuts import render
from django.views.decorators.cache import never_cache


@never_cache
def dashboard_view(request):
    return render(request, "superadmin/dashboard.html", {"active_page": "dashboard"})


@never_cache
def organizations_view(request):
    return render(
        request, "superadmin/organizations.html", {"active_page": "organizations"}
    )


@never_cache
def organization_detail_view(request, org_id):
    return render(
        request,
        "superadmin/organization_detail.html",
        {
            "active_page": "organizations",
            "org_id": str(org_id),
        },
    )


@never_cache
def users_view(request):
    return render(request, "superadmin/users.html", {"active_page": "users"})


@never_cache
def audits_view(request):
    return render(request, "superadmin/audits.html", {"active_page": "audits"})


@never_cache
def did_documents_view(request):
    return render(request, "superadmin/did_documents.html", {"active_page": "did_documents"})


@never_cache
def certificates_view(request):
    return render(request, "superadmin/certificates.html", {"active_page": "certificates"})
