"""Authentication routes."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.auth import get_current_user
from api.app.schemas.auth import LoginRequest
from api.app.schemas.common import SuccessResponse
from api.app.schemas.user import UserResponse
from api.app.services.audit import log_action
from api.app.services.auth import authenticate_user, create_tokens, refresh_tokens, revoke_token
from api.app.services.user import get_user_by_id
from api.app.utils.auth_cookies import (
    ACCESS_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    clear_auth_cookies,
    set_auth_cookies,
)
from api.database import get_db
from shared.logging import get_logger

logger = get_logger("auth_routes")

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/login",
    response_model=SuccessResponse,
)
async def login(
    login_data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse:
    """Authenticate user and set httpOnly JWT cookies."""
    client_ip = request.client.host if request.client else None
    user = await authenticate_user(db, login_data.username, login_data.password)
    if user is None:
        await log_action(
            db,
            action="LOGIN_FAILED",
            username=login_data.username,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
        )
        # Commit the audit row before raising — get_db rolls back on exception.
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    tokens = await create_tokens(user)
    set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
    await log_action(
        db,
        action="LOGIN",
        user_id=user.id,
        username=user.username,
        entity_type="User",
        entity_id=str(user.id),
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent"),
    )

    logger.info("login_success", username=user.username, user_id=user.id)
    return SuccessResponse(
        message="Login successful",
        data={"user": {"id": user.id, "username": user.username, "role": user.role}},
    )


@router.post("/logout", response_model=SuccessResponse)
async def logout(request: Request, response: Response) -> SuccessResponse:
    """Logout user and revoke tokens."""
    access_token = request.cookies.get(ACCESS_COOKIE_NAME)
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)

    if access_token:
        await revoke_token(access_token)
    if refresh_token:
        await revoke_token(refresh_token)

    clear_auth_cookies(response)
    logger.info("logout_success")
    return SuccessResponse(message="Logout successful")


@router.post("/refresh", response_model=SuccessResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse:
    """Refresh access token using refresh token."""
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )

    tokens = await refresh_tokens(refresh_token, db)
    if tokens is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
    return SuccessResponse(message="Token refreshed")


@router.get("/me", response_model=UserResponse)
async def me(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Get current authenticated user."""
    from fastapi import HTTPException

    user_payload = await get_current_user(request)
    if user_payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        user_id = int(user_payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return UserResponse.model_validate(user)
