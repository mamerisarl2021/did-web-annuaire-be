"""
Frontend views.

These are intentionally thin — they only render templates.
All data fetching and auth happen client-side via the JWT API (auth.js).
No session auth, no server-side auth checks.
"""

from django.shortcuts import render
from django.views.decorators.cache import never_cache


@never_cache
def login_view(request):
    return render(request, "frontend/login.html")


@never_cache
def register_view(request):
    return render(request, "frontend/register.html")


@never_cache
def forgot_password_view(request):
    return render(request, "frontend/forgot_password.html")


@never_cache
def password_reset_confirm_view(request, token):
    return render(request, "frontend/password_reset_confirm.html", {"token": token})


@never_cache
def activate_view(request, invitation_token):
    return render(request, "frontend/activate.html", {"invitation_token": invitation_token})


@never_cache
def dashboard_view(request):
    return render(request, "frontend/dashboard.html")

@never_cache
def resolve_view(request):
    return render(request, "frontend/resolve.html")

@never_cache
def search_view(request):
    return render(request, "frontend/search.html")