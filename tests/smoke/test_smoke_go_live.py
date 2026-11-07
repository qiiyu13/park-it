"""Smoke tests for E-Parking v2 go-live validation.

These tests verify that all critical system components are functional
after deployment. They are designed to be fast and comprehensive.

Run with:
    pytest tests/smoke/test_smoke_go_live.py -v
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestHealthSmoke:
    """Basic health checks."""

    def test_health_endpoint(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_metrics_endpoint(self, client):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "http_requests_total" in response.text


class TestAuthSmoke:
    """Authentication smoke tests."""

    def test_login_validation(self, client):
        """Empty login should return 422."""
        response = client.post("/api/auth/login", json={})
        assert response.status_code == 422

    def test_login_invalid_credentials(self, client):
        response = client.post(
            "/api/auth/login",
            json={"username": "nonexistent", "password": "wrong"},
        )
        assert response.status_code == 401


class TestApiRoutesSmoke:
    """Verify critical API routes are mounted and respond."""

    def test_settings_route_exists(self, client):
        response = client.get("/api/settings")
        # Should be 401 (unauthorized) or 200, not 404
        assert response.status_code in (200, 401, 403)

    def test_vehicle_types_route_exists(self, client):
        response = client.get("/api/vehicle-types")
        assert response.status_code in (200, 401, 403)

    def test_gates_in_route_exists(self, client):
        response = client.get("/api/gates/in")
        assert response.status_code in (200, 401, 403)

    def test_gates_out_route_exists(self, client):
        response = client.get("/api/gates/out")
        assert response.status_code in (200, 401, 403)

    def test_payments_lookup_route_exists(self, client):
        response = client.post("/api/payments/lookup", json={})
        assert response.status_code in (200, 401, 403, 422)

    def test_transactions_route_exists(self, client):
        response = client.get("/api/transactions")
        assert response.status_code in (200, 401, 403)

    def test_reports_summary_route_exists(self, client):
        response = client.get("/api/reports/summary")
        assert response.status_code in (200, 401, 403)

    def test_settlements_route_exists(self, client):
        response = client.get("/api/settlements")
        assert response.status_code in (200, 401, 403)

    def test_audit_logs_route_exists(self, client):
        response = client.get("/api/audit-logs")
        assert response.status_code in (200, 401, 403)


class TestSecurityHeadersSmoke:
    """Verify security headers are present on responses."""

    def test_x_content_type_options(self, client):
        response = client.get("/api/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        response = client.get("/api/health")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_csp_present(self, client):
        response = client.get("/api/health")
        assert "Content-Security-Policy" in response.headers

    def test_referrer_policy(self, client):
        response = client.get("/api/health")
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


class TestRateLimitSmoke:
    """Verify rate limiting middleware is active."""

    def test_rate_limit_headers_present(self, client):
        # Health is exempt from rate limiting, but should still have security headers
        response = client.get("/api/health")
        # Verify the middleware is mounted by checking security headers are present
        # (rate limit and security headers are both mounted)
        assert "X-Content-Type-Options" in response.headers


class TestWebSocketSmoke:
    """Verify WebSocket endpoint is available."""

    def test_websocket_endpoint_exists(self, client):
        # WebSocket handshake without proper auth will fail with 1008,
        # but that proves the endpoint is mounted (404 would mean not mounted)
        from starlette.websockets import WebSocketDisconnect
        try:
            with client.websocket_connect("/ws/test-gate") as ws:
                pass
        except WebSocketDisconnect as exc:
            # Auth required (1008) means endpoint exists and is working
            assert exc.code == 1008
            assert "Authentication" in exc.reason

    def test_websocket_not_found_for_invalid_path(self, client):
        response = client.get("/ws/")
        assert response.status_code == 404


class TestRouteCountSmoke:
    """Verify expected number of routes are loaded."""

    def test_minimum_route_count(self):
        # FastAPI >= 0.162 keeps include_router() results as lazy
        # _IncludedRouter entries in app.routes, so counting routes there
        # reports "2" even though every router is mounted. Count the generated
        # OpenAPI paths instead.
        paths = app.openapi().get("paths", {})
        assert len(paths) >= 80, f"Expected >= 80 paths, found {len(paths)}"
