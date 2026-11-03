"""Shared httpOnly auth cookie helpers.

Used by both the normal login routes and the setup wizard. Keeping the
lifetimes here means the JWT expiry settings and the cookie expiry can never
drift apart (they were hard-coded in two places before).
"""

from fastapi import Response

from shared.config import get_settings

ACCESS_COOKIE_NAME = "access_token"
REFRESH_COOKIE_NAME = "refresh_token"


def set_auth_cookies(
    response: Response, access_token: str, refresh_token: str
) -> None:
    settings = get_settings()
    is_secure = settings.app_env == "production"
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=settings.jwt_access_token_expire_minutes * 60,
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=settings.jwt_refresh_token_expire_days * 86400,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(key=ACCESS_COOKIE_NAME)
    response.delete_cookie(key=REFRESH_COOKIE_NAME)
