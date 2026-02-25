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
    return render(request, "superadmin/organizations.html", {"active_page": "organizations"})


@never_cache
def organization_detail_view(request, org_id):
    return render(request, "superadmin/organization_detail.html", {
        "active_page": "organizations",
        "org_id": str(org_id),
    })