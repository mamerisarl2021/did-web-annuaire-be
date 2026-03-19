"""
Universal Resolver integration.

Resolves DID documents via the DIF Universal Resolver REST API.

Configuration (Django settings):
  UNIVERSAL_RESOLVER_URL = "http://uni_resolver:8080"

API endpoint used:
  GET /1.0/identifiers/{did}
"""