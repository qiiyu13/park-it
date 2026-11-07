"""Shared fixtures for the integration tests (smoke + e2e).

The unit suites build and drop their own schema per test (``api/tests`` and
``workers/tests`` conftest), so in a full pytest session the database is empty
by the time these tests run. Bootstrap the model schema once per session so
these tests are order-independent and also run against an empty CI database.
"""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from api.app.models.base import Base
from shared.config import get_settings


@pytest.fixture(scope="session", autouse=True)
def _ensure_integration_schema() -> None:
    settings = get_settings()
    url = (
        f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/parking_test"
    )

    async def _create() -> None:
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_create())
