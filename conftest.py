"""Root pytest configuration shared by every test path.

``asyncio_mode=auto`` gives each test function its own event loop, but the
application caches connection objects in module-level singletons. A cached
asyncpg/redis connection opened under one test's loop and reused by the next
raises ``got Future attached to a different loop`` or ``Event loop is closed``.

The database engine handles this itself (``api/database.py`` switches to
NullPool under pytest). Redis caches a single client on a class attribute, so
drop it between tests. The socket is abandoned rather than awaited closed —
closing it would run on the wrong loop, which is the very thing being avoided.
Test processes are short-lived, so the abandoned handles cost nothing.
"""

import pytest


@pytest.fixture(autouse=True)
def _reset_loop_bound_singletons():
    yield

    from shared.redis import RedisClient

    RedisClient._redis = None

    import shared.redis as shared_redis

    if getattr(shared_redis, "_arq_pool", None) is not None:
        shared_redis._arq_pool = None
