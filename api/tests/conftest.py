"""Pytest configuration and fixtures."""

from collections.abc import AsyncGenerator

import pytest_asyncio
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app.models.base import Base
from shared.config import get_settings

settings = get_settings()


@pytest_asyncio.fixture(autouse=True)
async def _reset_rate_limits() -> AsyncGenerator[None, None]:
    """Drop rate-limit counters between tests.

    They live in Redis keyed by client IP and accumulate over the whole session,
    which intermittently 429'd late tests depending on run order.
    """
    client = aioredis.from_url(settings.redis_url)
    try:
        async for key in client.scan_iter("rate_limit:*"):
            await client.delete(key)
    finally:
        await client.aclose()
    yield

# Use a test database
TEST_DATABASE_URL = (
    f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}"
    f"@{settings.db_host}:{settings.db_port}/parking_test"
)


@pytest_asyncio.fixture(scope="function")
async def engine():
    """Create a test database engine (function-scoped to avoid loop mismatch)."""
    test_engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield test_engine
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh database session for each test."""
    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()
