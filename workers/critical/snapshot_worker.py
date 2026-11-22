"""Critical snapshot worker job."""

import json
import os
from datetime import datetime
from pathlib import Path

import httpx

from shared.logging import get_logger

logger = get_logger("snapshot_worker")

SNAPSHOT_DIR = Path(os.environ.get("SNAPSHOT_DIR", "/var/lib/parking/snapshots"))
try:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
except PermissionError:
    SNAPSHOT_DIR = Path("/tmp/parking-mock/snapshots")
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


async def take_snapshot(
    ctx,
    gate_id: str,
    camera_url: str,
    transaction_id: int | None = None,
    snapshot_type: str = "entry",
    camera_label: str | None = None,
    camera_username: str | None = None,
    camera_password: str | None = None,
    camera_auth_type: str = "none",
) -> dict:
    """Download or capture camera snapshot, save locally, and record in DB.

    Supports both HTTP snapshot URLs and RTSP streams.
    Broadcasts camera_snapshot WS event for exit snapshots so POS updates live.
    """
    logger.info(
        "take_snapshot_job",
        gate_id=gate_id,
        camera_url=camera_url,
        transaction_id=transaction_id,
        snapshot_type=snapshot_type,
    )

    from shared.config import get_settings

    if get_settings().mock_hardware:
        # 1x1 white JPEG placeholder
        image_data = bytes.fromhex(
            "ffd8ffe000104a46494600010101006000600000ffdb004300080606070605080707"
            "07090908"
            "0a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c283729"
            "2c30313434"
            "1f27393d38323c2e333432ffc0000b080001000101011100ffc4001f000001050101"
            "01010101000000000000000001020304050607080900ffc400b510000201030302040"
            "30502060101000000010002110321041231054113617122718132061491a1b14223"
            "2415528191a2b1c109233352f0d124e1f06272ffda0008010100003f00fbd8000000ffd9"
        )
        logger.info("mock_snapshot_used", gate_id=gate_id, snapshot_type=snapshot_type)
    else:
        is_rtsp = camera_url.lower().startswith("rtsp://")
        if is_rtsp:
            image_data = await _capture_rtsp(camera_url)
        else:
            image_data = await _download_http(
                camera_url,
                username=camera_username,
                password=camera_password,
                auth_type=camera_auth_type,
            )

    if image_data is None:
        from api.app.middleware.metrics import snapshot_jobs_total
        snapshot_jobs_total.labels(snapshot_type=snapshot_type, result="failure").inc()
        return {"status": "error", "message": "Snapshot capture failed"}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label_part = f"_{camera_label}" if camera_label else ""
    filename = f"{gate_id}_{snapshot_type}{label_part}_{timestamp}.jpg"
    filepath = SNAPSHOT_DIR / filename

    try:
        filepath.write_bytes(image_data)
    except Exception as e:
        logger.error("snapshot_save_failed", error=str(e), filepath=str(filepath))
        from api.app.middleware.metrics import snapshot_jobs_total
        snapshot_jobs_total.labels(snapshot_type=snapshot_type, result="failure").inc()
        return {"status": "error", "message": f"Save failed: {e}"}

    logger.info("snapshot_saved", filepath=str(filepath), size=len(image_data))

    snapshot_id = await _save_snapshot_record(
        gate_id=gate_id,
        filename=filename,
        filepath=str(filepath),
        file_size=len(image_data),
        snapshot_type=snapshot_type,
        transaction_id=transaction_id,
        camera_label=camera_label,
    )

    if snapshot_id:
        await _broadcast_snapshot(gate_id, snapshot_id, snapshot_type)

    from api.app.middleware.metrics import snapshot_jobs_total
    snapshot_jobs_total.labels(snapshot_type=snapshot_type, result="success").inc()
    return {
        "status": "success",
        "filepath": str(filepath),
        "filename": filename,
        "size": len(image_data),
        "snapshot_id": snapshot_id,
    }


async def _save_snapshot_record(
    *,
    gate_id: str,
    filename: str,
    filepath: str,
    file_size: int,
    snapshot_type: str,
    transaction_id: int | None,
    camera_label: str | None,
) -> int | None:
    """Create Snapshot row and update ParkingTransaction snapshot link."""
    try:
        from sqlalchemy import select

        from api.app.models import Gate, ParkingTransaction, Snapshot
        from api.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            gate_result = await db.execute(select(Gate).where(Gate.code == gate_id))
            gate = gate_result.scalar_one_or_none()
            if gate is None:
                logger.error("snapshot_gate_not_found", gate_id=gate_id)
                return None

            snapshot = Snapshot(
                parking_transaction_id=transaction_id,
                gate_id=gate.id,
                gate_type="out" if gate.direction == "OUT" else "in",
                snapshot_type=snapshot_type,
                filename=filename,
                file_path=filepath,
                file_size=file_size,
                camera_name=camera_label,
            )
            db.add(snapshot)
            await db.flush()
            await db.refresh(snapshot)
            snapshot_id = snapshot.id

            if transaction_id:
                tx = await db.get(ParkingTransaction, transaction_id)
                if tx:
                    if snapshot_type == "entry" and tx.entry_snapshot_id is None:
                        tx.entry_snapshot_id = snapshot_id
                    elif snapshot_type == "exit" and tx.exit_snapshot_id is None:
                        tx.exit_snapshot_id = snapshot_id

            await db.commit()
            logger.info("snapshot_db_saved", snapshot_id=snapshot_id, transaction_id=transaction_id)
            return snapshot_id
    except Exception as e:
        logger.error("snapshot_db_failed", error=str(e), gate_id=gate_id)
        return None


async def _broadcast_snapshot(gate_id: str, snapshot_id: int, snapshot_type: str) -> None:
    """Publish camera_snapshot so the POS can show entry/exit frames live."""
    try:
        from shared.redis import redis_client

        await redis_client.connect()
        payload = json.dumps({
            "type": "camera_snapshot",
            "snapshot_type": snapshot_type,
            "snapshot_url": f"/api/snapshots/{snapshot_id}/image",
        })
        await redis_client.client.publish(f"parking.events.{gate_id}", payload)
        logger.info(f"{snapshot_type}_snapshot_broadcast", gate_id=gate_id, snapshot_id=snapshot_id)
    except Exception as e:
        logger.error("snapshot_broadcast_failed", error=str(e), gate_id=gate_id)


async def _download_http(
    camera_url: str,
    username: str | None = None,
    password: str | None = None,
    auth_type: str = "none",
) -> bytes | None:
    """Download snapshot via HTTP with optional Basic or Digest auth."""
    auth = None
    if username and password:
        if auth_type == "digest":
            auth = httpx.DigestAuth(username, password)
        else:
            auth = httpx.BasicAuth(username, password)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(camera_url, auth=auth)
            response.raise_for_status()
            return response.content
    except Exception as e:
        logger.error("snapshot_download_failed", error=str(e), camera_url=camera_url)
        return None


async def _capture_rtsp(camera_url: str) -> bytes | None:
    """Capture frame from RTSP stream."""
    from workers.critical.rtsp_snapshot import capture_rtsp_frame_to_bytes

    try:
        return await capture_rtsp_frame_to_bytes(camera_url)
    except Exception as e:
        logger.error("rtsp_capture_failed", error=str(e), camera_url=camera_url)
        return None
