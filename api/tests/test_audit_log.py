"""Tests for audit logging service."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.routes.audit_logs import list_audit_logs
from api.app.services.audit import log_action
from api.app.utils.pagination import PaginationParams


class TestLogAction:
    @pytest.mark.asyncio
    async def test_create_basic_log(self, db_session: AsyncSession):
        """Should create a basic audit log entry."""
        log = await log_action(
            db_session,
            action="TEST_ACTION",
            user_id=1,
            username="admin",
            entity_type="Test",
            entity_id="123",
            details={"key": "value"},
            ip_address="192.168.1.1",
        )

        assert log is not None
        assert log.action == "TEST_ACTION"
        assert log.user_id == 1
        assert log.username == "admin"
        assert log.entity_type == "Test"
        assert log.entity_id == "123"
        assert log.details == {"key": "value"}
        assert log.ip_address == "192.168.1.1"

    @pytest.mark.asyncio
    async def test_create_minimal_log(self, db_session: AsyncSession):
        """Should create a log with minimal fields."""
        log = await log_action(
            db_session,
            action="MINIMAL_ACTION",
        )

        assert log is not None
        assert log.action == "MINIMAL_ACTION"
        assert log.user_id is None
        assert log.details == {}

    @pytest.mark.asyncio
    async def test_none_details_becomes_empty_dict(self, db_session: AsyncSession):
        """None details should be stored as empty dict."""
        log = await log_action(
            db_session,
            action="TEST",
            details=None,
        )

        assert log is not None
        assert log.details == {}


class TestListAuditLogsRoute:
    """The list route was passing `pagination` positionally into `count_stmt`.

    SQLAlchemy then tried to execute a PaginationParams model, so GET
    /api/audit-logs raised for every caller. No test reached the handler —
    the smoke test only asserts the route is not 404 and stops at the 401.
    """

    @pytest.mark.asyncio
    async def test_list_returns_logs(self, db_session: AsyncSession):
        await log_action(db_session, action="LIST_ME", entity_type="Widget")

        result = await list_audit_logs(
            request=None,
            db=db_session,
            pagination=PaginationParams(skip=0, limit=10),
        )

        assert result.total >= 1
        assert any(item.action == "LIST_ME" for item in result.items)

    @pytest.mark.asyncio
    async def test_list_honors_pagination_and_filter(self, db_session: AsyncSession):
        for i in range(3):
            await log_action(db_session, action="PAGED", entity_type=f"E{i}")

        page = await list_audit_logs(
            request=None,
            db=db_session,
            pagination=PaginationParams(skip=0, limit=2),
            action="PAGED",
        )

        assert len(page.items) == 2, "limit was ignored — pagination not wired through"
        assert page.total >= 3
        assert all(item.action == "PAGED" for item in page.items)
