"""
DID Document frontend views.

Thin template-rendering views. All data is fetched
client-side via the Documents API using JWT auth.
"""

from django.views.decorators.cache import never_cache
from django.shortcuts import render


@never_cache
def documents_view(request):
    return render(request, "orgadmin/documents.html", {"active_page": "documents"})


@never_cache
def document_detail_view(request, doc_id):
    return render(request, "orgadmin/document_detail.html", {
        "active_page": "documents",
        "doc_id": doc_id,
    })