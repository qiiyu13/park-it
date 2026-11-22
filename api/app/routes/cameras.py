"""Camera management routes."""

import base64

import httpx
from fastapi import Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.auth import require_admin, require_auth
from api.app.models.camera import Camera
from api.app.routes.crud_factory import create_crud_router
from api.app.schemas.camera import CameraCreate, CameraResponse, CameraUpdate
from api.database import get_db
from shared.logging import get_logger

logger = get_logger("camera_routes")

router = create_crud_router(
    model=Camera,
    schema_create=CameraCreate,
    schema_update=CameraUpdate,
    schema_response=CameraResponse,
    prefix="/cameras",
    tags=["Cameras"],
    auth_dependency=require_admin,
    use_pagination=False,
    not_found_detail="Camera not found",
)


@router.get("/{camera_id}/test")
async def test_camera(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> dict:
    """Proxy a snapshot from this camera and return it as base64 JPEG.

    Fetches from the server's network perspective so cameras on isolated
    VLANs (unreachable from the browser) can still be verified.
    """
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    is_rtsp = camera.type == "rtsp" or (
        camera.rtsp_url is not None and camera.snapshot_url is None
    )

    if is_rtsp:
        url = camera.rtsp_url
        if not url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No RTSP URL configured")
        from workers.critical.rtsp_snapshot import capture_rtsp_frame_to_bytes
        image_bytes = await capture_rtsp_frame_to_bytes(url)
    else:
        url = camera.snapshot_url
        if not url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No snapshot URL configured")
        auth = None
        if camera.username and camera.password:
            if camera.auth_type == "digest":
                auth = httpx.DigestAuth(camera.username, camera.password)
            else:
                auth = httpx.BasicAuth(camera.username, camera.password)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, auth=auth)
                response.raise_for_status()
                image_bytes = response.content
        except httpx.HTTPStatusError as e:
            logger.warning("camera_test_http_error", camera_id=camera_id, status=e.response.status_code)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Camera returned HTTP {e.response.status_code}",
            )
        except Exception as e:
            logger.warning("camera_test_failed", camera_id=camera_id, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to reach camera: {e}",
            )

    if image_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Camera did not return an image",
        )

    logger.info("camera_test_ok", camera_id=camera_id, size=len(image_bytes))
    return {
        "success": True,
        "snapshot": base64.b64encode(image_bytes).decode(),
    }


@router.get("/{camera_id}/snapshot")
async def camera_snapshot(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
) -> Response:
    """Serve the latest JPEG so browsers can show a live-ish preview.

    Browsers cannot render RTSP in an <img>, and camera credentials must not be
    exposed to the operator page — the server proxies one frame per request and
    the POS refreshes it every couple of seconds.
    """
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    url = camera.rtsp_url or camera.snapshot_url
    if not url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Camera has no URL configured")

    if url.lower().startswith("rtsp://"):
        from workers.critical.rtsp_snapshot import capture_rtsp_frame_to_bytes

        image_bytes = await capture_rtsp_frame_to_bytes(url)
        if not image_bytes:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Camera did not return an image")
        return Response(content=image_bytes, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    auth = None
    if camera.username and camera.password:
        auth = httpx.DigestAuth(camera.username, camera.password) if camera.auth_type == "digest" else httpx.BasicAuth(camera.username, camera.password)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, auth=auth)
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("camera_snapshot_failed", camera_id=camera_id, error=str(exc))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"snapshot failed: {exc}"[:200])

    return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/jpeg"), headers={"Cache-Control": "no-store"})


@router.get("/{camera_id}/stream")
async def camera_stream(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Live MJPEG stream (multipart/x-mixed-replace) for the operator POS.

    Browsers cannot play RTSP; this pipes ffmpeg frames to an <img> tag. LAN
    only, one ffmpeg process per viewer, ~5 fps.
    """
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    url = camera.rtsp_url or camera.snapshot_url
    if not url or not url.lower().startswith("rtsp://"):
        raise HTTPException(status_code=400, detail="Live stream needs an RTSP URL")

    import asyncio
    import shutil

    from fastapi.responses import StreamingResponse

    ffmpeg = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"

    async def frames():
        proc = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-rtsp_transport", "tcp",
            "-i", url,
            "-an",
            "-f", "mpjpeg",
            "-q:v", "6",
            "-r", "5",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary=--ffmpeg",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
