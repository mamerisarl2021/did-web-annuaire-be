"""
Custom middleware.

RequestContextMiddleware: stores the client IP address in a thread-local
so that audit log entries created deep in the service layer can include
the IP without needing the ``request`` object passed through every call.
"""

from src.common.request_context import clear_request_context, set_request_ip


class RequestContextMiddleware:
    """
    Extracts the client IP from the request (handling X-Forwarded-For
    from nginx) and stores it in thread-local storage.

    Add to MIDDLEWARE *after* SecurityMiddleware, *before* any app logic:

        MIDDLEWARE = [
            ...
            "django.middleware.security.SecurityMiddleware",
            "src.common.middleware.RequestContextMiddleware",
            ...
        ]
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Extract IP — X-Forwarded-For is set by nginx
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            ip = xff.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR")

        set_request_ip(ip)

        try:
            response = self.get_response(request)
        finally:
            clear_request_context()

        return response
