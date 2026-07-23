"""JWT token endpoints with explicit rate limits."""

from ninja_extra import ControllerBase, api_controller, http_post
from ninja_extra.permissions import AllowAny
from ninja_jwt.controller import TokenObtainPairController, TokenVerificationController
from ninja_jwt.schema_control import SchemaControl
from ninja_jwt.settings import api_settings

from src.common.throttling import (
    login_throttle,
    token_refresh_throttle,
    token_verify_throttle,
)

schema = SchemaControl(api_settings)


@api_controller("/token", permissions=[AllowAny], tags=["token"], auth=None)
class ThrottledNinjaJWTController(
    ControllerBase, TokenVerificationController, TokenObtainPairController
):
    auto_import = False

    @http_post(
        "/pair",
        response=schema.obtain_pair_schema.get_response_schema(),
        url_name="token_obtain_pair",
        operation_id="token_obtain_pair",
        throttle=login_throttle,
    )
    def obtain_token(self, user_token: schema.obtain_pair_schema):
        user_token.check_user_authentication_rule()
        return user_token.to_response_schema()

    @http_post(
        "/refresh",
        response=schema.obtain_pair_refresh_schema.get_response_schema(),
        url_name="token_refresh",
        operation_id="token_refresh",
        throttle=token_refresh_throttle,
    )
    def refresh_token(self, refresh_token: schema.obtain_pair_refresh_schema):
        return refresh_token.to_response_schema()

    @http_post(
        "/verify",
        response={200: schema.verify_schema.get_response_schema()},
        url_name="token_verify",
        operation_id="token_verify",
        throttle=token_verify_throttle,
    )
    def verify_token(self, token: schema.verify_schema):
        return token.to_response_schema()
