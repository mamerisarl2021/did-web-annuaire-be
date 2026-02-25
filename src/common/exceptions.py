"""
Application exceptions and django-ninja error handlers.

Services raise these exceptions; the API layer catches them
via ninja's exception handlers and returns proper HTTP responses.
"""

import structlog
from django.http import HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.errors import HttpError

logger = structlog.get_logger(__name__)


class ApplicationError(Exception):
    """Base for all business-logic errors."""

    def __init__(self, message: str, extra: dict | None = None):
        super().__init__(message)
        self.message = message
        self.extra = extra or {}


class NotFoundError(ApplicationError):
    """Resource not found."""
    pass


class PermissionDeniedError(ApplicationError):
    """User lacks required permissions."""
    pass


class ValidationError(ApplicationError):
    """Business rule validation failed."""
    pass


class ConflictError(ApplicationError):
    """Resource already exists or state conflict."""
    pass


class ExternalServiceError(ApplicationError):
    """An external service (registrar, signserver, cert service) failed."""
    pass


def configure_exception_handlers(api: NinjaAPI) -> None:
    """Register custom exception handlers on a NinjaAPI instance."""

    @api.exception_handler(NotFoundError)
    def handle_not_found(request: HttpRequest, exc: NotFoundError) -> HttpResponse:
        return api.create_response(
            request,
            {"detail": exc.message, **exc.extra},
            status=404,
        )

    @api.exception_handler(PermissionDeniedError)
    def handle_permission_denied(request: HttpRequest, exc: PermissionDeniedError) -> HttpResponse:
        return api.create_response(
            request,
            {"detail": exc.message},
            status=403,
        )

    @api.exception_handler(ValidationError)
    def handle_validation(request: HttpRequest, exc: ValidationError) -> HttpResponse:
        return api.create_response(
            request,
            {"detail": exc.message, **exc.extra},
            status=400,
        )

    @api.exception_handler(ConflictError)
    def handle_conflict(request: HttpRequest, exc: ConflictError) -> HttpResponse:
        return api.create_response(
            request,
            {"detail": exc.message, **exc.extra},
            status=409,
        )

    @api.exception_handler(ExternalServiceError)
    def handle_external_service(request: HttpRequest, exc: ExternalServiceError) -> HttpResponse:
        logger.error("external_service_error", message=exc.message, **exc.extra)
        return api.create_response(
            request,
            {"detail": "An external service is unavailable. Please try again."},
            status=502,
        )