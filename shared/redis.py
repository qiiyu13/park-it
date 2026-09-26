"""Async Redis client with Streams and Pub/Sub helpers."""

from typing import Any

import redis.asyncio as aioredis

from shared.config import get_settings


class RedisClient:
    """Async Redis client singleton."""

    _instance: "RedisClient | None" = None
    _redis: aioredis.Redis | None = None

    def __new__(cls) -> "RedisClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def connect(self) -> None:
        """Establish Redis connection."""
        if self._redis is None:
            settings = get_settings()
            self._redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
            )

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    @property
    def client(self) -> aioredis.Redis:
        """Return the Redis client instance."""
        if self._redis is None:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._redis

    # ------------------------------------------------------------------
    # Pub/Sub helpers (fire-and-forget events)
    # ------------------------------------------------------------------

    async def publish(self, channel: str, message: str) -> int:
        """Publish a message to a Pub/Sub channel."""
        return await self.client.publish(channel, message)

    # ------------------------------------------------------------------
    # Streams helpers (ACK-based commands)
    # ------------------------------------------------------------------

    async def xadd(
        self,
        stream: str,
        fields: dict[str, str],
        maxlen: int | None = None,
    ) -> str:
        """Add a message to a Redis Stream."""
        if maxlen:
            return await self.client.xadd(stream, fields, maxlen=maxlen)  # type: ignore[arg-type]
        return await self.client.xadd(stream, fields)  # type: ignore[arg-type]

    async def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int = 1,
        block: int | None = 5000,
    ) -> list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]]:
        """Read from a consumer group."""
        return await self.client.xreadgroup(  # type: ignore[return-value]
            groupname=groupname,
            consumername=consumername,
            streams=streams,
            count=count,
            block=block,
        )

    async def xack(self, stream: str, groupname: str, *ids: str) -> int:
        """Acknowledge messages in a stream."""
        return await self.client.xack(stream, groupname, *ids)

    async def xgroup_create(
        self,
        stream: str,
        groupname: str,
        id_: str = "$",
        mkstream: bool = False,
    ) -> bytes:
        """Create a consumer group."""
        return await self.client.xgroup_create(  # type: ignore[return-value]
            stream, groupname, id_, mkstream=mkstream
        )

    async def xgroup_createconsumer(
        self, stream: str, groupname: str, consumername: str
    ) -> int:
        """Create a consumer within a group."""
        return await self.client.xgroup_createconsumer(  # type: ignore[return-value]
            stream, groupname, consumername
        )

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    async def get(self, key: str) -> str | None:
        """Get a value from Redis."""
        return await self.client.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        """Set a value in Redis with optional TTL.

        ``nx=True`` makes it atomic "set if absent" (returns False when the
        key already exists) — used as a lock/claim primitive.
        """
        return await self.client.set(key, value, ex=ex, nx=nx)

    async def delete(self, *keys: str) -> int:
        """Delete keys from Redis."""
        return await self.client.delete(*keys)

    async def hget(self, name: str, key: str) -> str | None:
        """Get a hash field."""
        return await self.client.hget(name, key)

    async def hset(self, name: str, mapping: dict[str, Any]) -> int:
        """Set hash fields."""
        return await self.client.hset(name, mapping=mapping)  # type: ignore[arg-type]

    async def hdel(self, name: str, *keys: str) -> int:
        """Delete hash fields."""
        return await self.client.hdel(name, *keys)

    async def expire(self, key: str, seconds: int) -> bool:
        """Set TTL on a key."""
        return await self.client.expire(key, seconds)

    # ------------------------------------------------------------------
    # Pattern scan helpers
    # ------------------------------------------------------------------

    async def cache_delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern."""
        keys = []
        async for key in self.client.scan_iter(match=pattern):
            keys.append(key)
        if keys:
            return await self.delete(*keys)
        return 0


# Global instance
redis_client = RedisClient()


# ---------------------------------------------------------------------------
# ARQ pool — separate from raw Redis client because ARQ uses its own framing
# ---------------------------------------------------------------------------

_arq_pool: Any | None = None
_arq_pool_lock: Any | None = None


async def get_arq_redis(queue_name: str = "arq:queue:critical") -> Any:
    """Return cached ARQ pool for enqueueing jobs.

    Default queue is critical (print, snapshot). Pass queue_name='arq:queue:background'
    for settlement/cleanup jobs.
    """
    global _arq_pool, _arq_pool_lock
    import asyncio

    from arq import create_pool
    from arq.connections import RedisSettings

    if _arq_pool_lock is None:
        _arq_pool_lock = asyncio.Lock()

    async with _arq_pool_lock:
        if _arq_pool is None:
            settings = get_settings()
            _arq_pool = await create_pool(
                RedisSettings(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    database=settings.redis_db,
                    password=settings.redis_password or None,
                ),
                default_queue_name=queue_name,
            )
    return _arq_pool
