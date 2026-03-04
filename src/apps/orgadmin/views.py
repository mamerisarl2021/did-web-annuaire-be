"""
Org admin views.

Thin template renderers. All data fetched client-side via JWT API.
"""

from django.shortcuts import render
from django.views.decorators.cache import never_cache


@never_cache
def dashboard_view(request):
    return render(request, "orgadmin/dashboard.html", {"active_page": "dashboard"})


@never_cache
def members_view(request):
    return render(request, "orgadmin/members.html", {"active_page": "members"})


@never_cache
def settings_view(request):
    return render(request, "orgadmin/settings.html", {"active_page": "settings"})