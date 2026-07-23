"""
Shared API rate limiters (django-ninja).

Per-endpoint throttles on auth/token routes are stricter than the API defaults.
"""

from ninja.throttling import AnonRateThrottle, AuthRateThrottle

# ── Global baselines (NinjaExtraAPI) ────────────────────────────────────────

anon_baseline = AnonRateThrottle("120/m")
auth_baseline = AuthRateThrottle("600/m")

# ── JWT / login ─────────────────────────────────────────────────────────────

login_throttle = AnonRateThrottle("10/m")
token_refresh_throttle = AnonRateThrottle("30/m")
token_verify_throttle = AnonRateThrottle("60/m")

# ── Registration & activation ───────────────────────────────────────────────

register_throttle = AnonRateThrottle("5/h")
activation_setup_throttle = AnonRateThrottle("20/m")
activation_verify_throttle = AnonRateThrottle("10/m")

# ── Password flows ──────────────────────────────────────────────────────────

password_reset_request_throttle = AnonRateThrottle("5/h")
password_reset_confirm_throttle = AnonRateThrottle("10/m")
password_change_throttle = AuthRateThrottle("10/h")

# ── Machine clients & public API ────────────────────────────────────────────

m2m_token_throttle = AnonRateThrottle("20/m")
public_api_throttle = AnonRateThrottle("60/m")
