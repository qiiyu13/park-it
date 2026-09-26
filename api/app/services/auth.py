"""Authentication service."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.models.user import User
from api.app.utils.jwt import create_access_token, create_refresh_token, decode_token
from api.app.utils.password import verify_password
from shared.logging import get_logger
from shared.redis import redis_client

logger = get_logger("auth_service")


def _denylist_key(jti: str) -> str:
    """Redis key for token denylist."""
    return f"jwt:denylist:{jti}"


async def authenticate_user(
    db: AsyncSession,
    username: str,
    password: str,
) -> User | None:
    """Authenticate a user by username and password."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None:
        logger.warning("auth_failed_user_not_found", username=username)
        return None

    if not user.is_active:
        logger.warning("auth_failed_user_inactive", username=username)
        return None

    if not verify_password(password, user.password_hash):
        logger.warning("auth_failed_wrong_password", username=username)
        return None

    logger.info("auth_success", username=username, user_id=user.id)
    return user


async def create_tokens(user: User) -> dict[str, str]:
    """Create access and refresh tokens for a user."""
    token_data = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
    }
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info("tokens_created", user_id=user.id)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


async def refresh_tokens(refresh_token: str) -> dict[str, str] | None:
    """Rotate refresh token and return new token pair."""
    try:
        payload = decode_token(refresh_token)
    except Exception:
        logger.warning("refresh_failed_invalid_token")
        return None

    if payload.get("type") != "refresh":
        logger.warning("refresh_failed_wrong_token_type")
        return None

    jti = payload.get("jti")
    if jti and await _is_token_revoked(jti):
        logger.warning("refresh_failed_revoked_token")
        return None

    # Revoke old refresh token
    if jti:
        await _revoke_token(jti, payload.get("exp", 0))

    token_data = {
        "sub": payload["sub"],
        "username": payload.get("username", ""),
        "role": payload.get("role", "operator"),
    }
    new_access = create_access_token(token_data)
    new_refresh = create_refresh_token(token_data)

    logger.info("tokens_refreshed", user_id=payload["sub"])
    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
    }


async def revoke_token(token: str) -> bool:
    """Revoke a token by adding it to the Redis denylist."""
    try:
        payload = decode_token(token)
    except Exception:
        return False

    jti = payload.get("jti")
    if jti is None:
        # Generate a simple jti from token hash if missing
        import hashlib
        jti = hashlib.sha256(token.encode()).hexdigest()[:32]

    exp = payload.get("exp", 0)
    await _revoke_token(jti, exp)
    return True


async def _revoke_token(jti: str, exp: int) -> None:
    """Add token jti to Redis denylist with TTL matching expiry."""
    import time
    ttl = max(0, int(exp) - int(time.time()))
    if ttl > 0:
        try:
            await redis_client.connect()
            await redis_client.set(_denylist_key(jti), "1", ex=ttl)
        except Exception as e:
            # Best-effort: a failed logout must not 500. The token expires
            # on its own; log so the gap is visible.
            logger.warning("token_revoke_failed", jti=jti, error=str(e))


async def _is_token_revoked(jti: str) -> bool:
    """Check if a token jti is in the denylist.

    Fails OPEN on Redis errors: a Redis blip must not take down every
    authenticated request (and every WS handshake) at once. Tokens are
    short-lived anyway, so the exposure window equals the access-token TTL.
    """
    try:
        await redis_client.connect()
        result = await redis_client.get(_denylist_key(jti))
        return result is not None
    except Exception as e:
        logger.warning("token_denylist_check_failed_fail_open", jti=jti, error=str(e))
        return False


async def is_token_valid(token: str) -> dict[str, Any] | None:
    """Decode an access token and verify it is not revoked.

    Enforces ``type == "access"`` so a long-lived refresh token cannot be
    replayed in the access_token cookie to authenticate API/WS requests.
    """
    try:
        payload = decode_token(token)
    except Exception:
        return None

    if payload.get("type") != "access":
        return None

    jti = payload.get("jti")
    if jti and await _is_token_revoked(jti):
        return None

    return payload
