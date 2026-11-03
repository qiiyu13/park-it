"""Rate limiting middleware using Redis with in-memory fallback.

Provides configurable rate limits per endpoint path pattern.
Falls back to in-memory tracking when Redis is unavailable.
"""

import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from shared.logging import get_logger
from shared.redis import redis_client

logger = get_logger("rate_limit")

# Default limits: (requests, window_seconds)
DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    "/api/auth/login": (5, 60),
    "/api/auth/refresh": (10, 60),
    "/api/payments/": (30, 60),
    # Enrollment codes are short enough to type; cap guessing attempts.
    "/api/setup/enroll": (10, 60),
}

DEFAULT_FALLBACK = (100, 60)  # 100 req/min for everything else

# Paths that are exempt from rate limiting
EXEMPT_PATHS = [
    "/api/health",
    "/metrics",
    "/docs",
    "/openapi.json",
]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces rate limits per IP address.

    Uses Redis token bucket algorithm for distributed rate limiting.
    """

    def __init__(
        self,
        app,
        limits: dict[str, tuple[int, int]] | None = None,
        fallback_limit: tuple[int, int] | None = None,
    ):
        super().__init__(app)
        self.limits = limits or DEFAULT_LIMITS
        self.fallback_limit = fallback_limit or DEFAULT_FALLBACK
        # In-memory fallback when Redis is unavailable
        self._mem_buckets: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Test-only switch (RATE_LIMIT_DISABLED=true) for browser suites that
        # legitimately exercise login many times from one IP.
        from shared.config import get_settings

        if get_settings().rate_limit_disabled:
            return await call_next(request)

        # Skip exempt paths
        if any(path.startswith(exempt) for exempt in EXEMPT_PATHS):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        limit_key = self._match_limit(path)
        max_requests, window = self.limits.get(limit_key, self.fallback_limit)

        # Build Redis key
        redis_key = f"rate_limit:{client_ip}:{limit_key or 'default'}"

        # Check rate limit via Redis
        is_allowed, retry_after = await self._check_limit(
            redis_key, max_requests, window
        )

        if not is_allowed:
            logger.warning(
                "rate_limit_exceeded",
                client_ip=client_ip,
                path=path,
                limit=max_requests,
                window=window,
            )
            return Response(
                content='{"detail":"Too many requests","retry_after":' + str(retry_after) + '}',
                status_code=429,
                headers={
                    "Content-Type": "application/json",
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Window": str(window),
                },
            )

        # Add rate limit headers to response
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Window"] = str(window)
        return response

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _match_limit(self, path: str) -> str | None:
        """Find the best matching limit key for the path."""
        for key in self.limits:
            if path.startswith(key):
                return key
        return None

    async def _check_limit(
        self,
        redis_key: str,
        max_requests: int,
        window: int,
    ) -> tuple[bool, int]:
        """Check if request is within rate limit using Redis.

        Uses sliding window counter approach:
        - Store timestamps in a Redis sorted set
        - Remove entries older than window
        - Count remaining entries
        - If count < max_requests, allow and add new entry

        Returns:
            (is_allowed, retry_after_seconds)
        """
        try:
            await redis_client.connect()
            redis = redis_client.client
            now = time.time()
            window_start = now - window

            # Remove old entries
            await redis.zremrangebyscore(redis_key, 0, window_start)

            # Count current entries
            current_count = await redis.zcard(redis_key)

            if current_count >= max_requests:
                # Find when the oldest entry in window expires
                oldest_entries = await redis.zrange(redis_key, 0, 0, withscores=True)
                if oldest_entries:
                    oldest_timestamp = oldest_entries[0][1]
                    retry_after = max(1, int(oldest_timestamp + window - now))
                else:
                    retry_after = window
                return False, retry_after

            # Add current request timestamp
            await redis.zadd(redis_key, {str(now): now})
            # Set expiry on key to auto-cleanup
            await redis.expire(redis_key, window + 1)

            return True, 0

        except Exception as e:
            # Redis unavailable — fall back to in-memory rate limiting
            logger.warning("rate_limit_redis_fallback", error=str(e), redis_key=redis_key)
            return self._check_limit_memory(redis_key, max_requests, window)

    def _check_limit_memory(
        self,
        key: str,
        max_requests: int,
        window: int,
    ) -> tuple[bool, int]:
        """In-memory fallback rate limiter (per-process, not distributed)."""
        now = time.time()
        window_start = now - window

        # Clean old entries
        self._mem_buckets[key] = [
            ts for ts in self._mem_buckets[key] if ts > window_start
        ]

        if len(self._mem_buckets[key]) >= max_requests:
            oldest = self._mem_buckets[key][0] if self._mem_buckets[key] else now
            retry_after = max(1, int(oldest + window - now))
            return False, retry_after

        self._mem_buckets[key].append(now)
        return True, 0
