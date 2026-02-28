"""
Certificate frontend views.

These are thin template-rendering views. All data is fetched
client-side via the Certificate API using JWT auth.
"""

from django.views.decorators.cache import never_cache
from django.shortcuts import render


@never_cache
def certificates_view(request):
    return render(request, "orgadmin/certificates.html")


@never_cache
def certificate_detail_view(request, cert_id):
    return render(request, "orgadmin/certificate_detail.html", {"cert_id": cert_id})
