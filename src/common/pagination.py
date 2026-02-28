"""
Pagination utilities for django-ninja endpoints.
"""

from typing import Any

from django.db.models import QuerySet
from ninja import Schema


class PaginatedResponse(Schema):
    count: int
    next: str | None = None
    previous: str | None = None
    results: list[Any]


def paginate_queryset(
    queryset: QuerySet,
    page: int = 1,
    page_size: int = 25,
    max_page_size: int = 100,
) -> tuple[QuerySet, int]:
    """
    Apply offset pagination to a queryset.

    Returns (sliced_queryset, total_count).
    """
    page_size = min(page_size, max_page_size)
    page = max(page, 1)
    offset = (page - 1) * page_size

    total = queryset.count()
    sliced = queryset[offset : offset + page_size]

    return sliced, total