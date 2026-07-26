"""Async database configuration.

NOTE: This module is for api/ ONLY. Daemons must never import this.
"""

import sys
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.app.models.base import Base
from shared.config import get_settings

settings = get_settings()

# pytest-asyncio (asyncio_mode=auto) gives every test its own event loop, but
# this engine is module-level, so a pooled asyncpg connection opened under one
# test's loop gets handed to the next test's loop and raises "attached to a
# different loop". NullPool opens and closes per checkout, which costs a
# connection per request but keeps the engine loop-agnostic. Tests only.
#
# Detected via sys.modules, not PYTEST_CURRENT_TEST — that variable is only set
# once a test is executing, and this module is imported during collection.
_UNDER_PYTEST = "pytest" in sys.modules or settings.app_env == "test"

_pool_args = (
    {"poolclass": NullPool}
    if _UNDER_PYTEST
    else {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_recycle": 1800,
    }
)

# Async engine.
# `statement_cache_size=0` + `prepared_statement_cache_size=0` keep the engine
# safe behind pgbouncer in transaction pooling mode (asyncpg requirement).
# `pool_recycle=1800` drops connections older than 30 min to avoid stale
# sockets after long idle (e.g. firewall NAT drop, postgres restart).
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    },
    **_pool_args,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Re-export Base for Alembic and other consumers
__all__ = ["Base", "engine", "AsyncSessionLocal", "get_db"]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for FastAPI dependency injection.

    Automatically commits on success or rolls back on exception.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
