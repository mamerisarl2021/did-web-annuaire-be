"""
Shared exception classes and Ninja exception handler configuration.
"""

import structlog
from django.http import JsonResponse

logger = structlog.get_logger(__name__)


class ApplicationError(Exception):
    """Base exception for all application-level errors."""

    def __init__(self, message: str = "An error occurred.", status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ValidationError(ApplicationError):
    def __init__(self, message: str = "Validation error."):
        super().__init__(message=message, status_code=400)


class NotFoundError(ApplicationError):
    def __init__(self, message: str = "Resource not found."):
        super().__init__(message=message, status_code=404)


class ConflictError(ApplicationError):
    def __init__(self, message: str = "Resource conflict."):
        super().__init__(message=message, status_code=409)


class PermissionDeniedError(ApplicationError):
    def __init__(self, message: str = "Permission denied."):
        super().__init__(message=message, status_code=403)


def configure_exception_handlers(api):
    """Register exception handlers on a NinjaExtraAPI instance."""

    @api.exception_handler(ApplicationError)
    def handle_application_error(request, exc: ApplicationError):
        return JsonResponse({"detail": exc.message}, status=exc.status_code)

    @api.exception_handler(Exception)
    def handle_unexpected_error(request, exc: Exception):
        logger.exception("unhandled_error", error=str(exc))
        return JsonResponse(
            {"detail": "An unexpected error occurred."},
            status=500,
        )