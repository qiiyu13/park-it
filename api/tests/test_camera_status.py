"""Camera reachability: summary pills and the Test Kamera dialog."""

import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.main import app
from api.app.middleware.auth import require_admin
from api.app.models.camera import Camera
from api.app.routes import cameras as cameras_route
from api.app.routes.cameras import _camera_reachable
from api.database import get_db


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_admin] = lambda: {"sub": "1", "role": "admin"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def open_port():
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    yield server.sockets[0].getsockname()[1]
    server.close()


@pytest_asyncio.fixture
async def closed_port():
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    return port


async def test_password_containing_at_sign_still_finds_host(open_port: int):
    assert await _camera_reachable(f"rtsp://admin:@dm@127.0.0.1:{open_port}/stream")


@pytest.mark.parametrize("url", [None, "", "rtsp://", "rtsp://h:notaport/", "rtsp://[bad/"])
async def test_malformed_url_is_unreachable(url):
    assert await _camera_reachable(url) is False


async def test_hanging_host_is_bounded_by_timeout(monkeypatch):
    async def hang(*_):
        await asyncio.sleep(60)

    monkeypatch.setattr(asyncio, "open_connection", hang)
    assert await _camera_reachable("rtsp://10.0.0.1/", timeout=0.05) is False


async def test_summary_reports_each_active_camera(
    client: AsyncClient, db_session: AsyncSession, open_port: int, closed_port: int
):
    up = Camera(name="up", rtsp_url=f"rtsp://127.0.0.1:{open_port}/")
    down = Camera(name="down", rtsp_url=f"rtsp://127.0.0.1:{closed_port}/")
    off = Camera(name="off", rtsp_url=f"rtsp://127.0.0.1:{open_port}/", is_active=False)
    db_session.add_all([up, down, off])
    await db_session.commit()

    response = await client.get("/api/cameras/status/summary")

    assert response.status_code == 200
    assert response.json() == {str(up.id): True, str(down.id): False}


async def test_dialog_distinguishes_disconnected_from_no_image(
    client: AsyncClient, db_session: AsyncSession, open_port: int, closed_port: int, monkeypatch
):
    down = Camera(name="down", rtsp_url=f"rtsp://127.0.0.1:{closed_port}/")
    up = Camera(name="up", rtsp_url=f"rtsp://127.0.0.1:{open_port}/")
    db_session.add_all([down, up])
    await db_session.commit()

    response = await client.get(f"/api/cameras/{down.id}/test")
    assert (response.status_code, response.json()["detail"]) == (502, "Kamera tidak terhubung")

    async def no_frame(_url):
        return None

    monkeypatch.setattr("workers.critical.rtsp_snapshot.capture_rtsp_frame_to_bytes", no_frame)
    response = await client.get(f"/api/cameras/{up.id}/test")
    assert response.status_code == 502
    assert "tidak mengirim gambar" in response.json()["detail"]
    assert cameras_route._camera_source(up) == (up.rtsp_url, True)
