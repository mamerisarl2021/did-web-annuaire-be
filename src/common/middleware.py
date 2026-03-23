"""
Intergiciel personnalisé.

RequestContextMiddleware : stocke l'adresse IP du client dans une variable locale au thread
afin que les entrées de journal d'audit créées profondément dans la couche de service
puissent inclure l'IP sans avoir besoin de passer l'objet ``request`` à chaque appel.
"""

from src.common.request_context import clear_request_context, set_request_ip


class RequestContextMiddleware:
    """
    Extrait l'IP du client de la requête (gère X-Forwarded-For
    depuis nginx) et la stocke dans le stockage local au thread.

    Ajouter à MIDDLEWARE *après* SecurityMiddleware, *avant* toute logique d'application :

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
        # Extrait l'IP — X-Forwarded-For est défini par nginx
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
