"""
Certificate frontend views.

Thin template-rendering views. All data is fetched
client-side via the Certificate API using JWT auth.
"""

from django.views.decorators.cache import never_cache
from django.shortcuts import render


@never_cache
def certificates_view(request):
    return render(request, "certificates.html", {"active_page": "certificates"})


@never_cache
def certificate_detail_view(request, cert_id):
    return render(
        request,
        "certificate_detail.html",
        {
            "active_page": "certificates",
            "cert_id": cert_id,
        },
    )
