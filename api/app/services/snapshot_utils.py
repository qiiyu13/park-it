"""Shared snapshot enqueue utilities."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.logging import get_logger

logger = get_logger("snapshot_utils")


async def resolve_gate_cameras(db: AsyncSession, gate) -> list[dict]:
    """Camera configs for a gate: inline ``cameras[]`` + referenced records.

    Cameras are shared devices: a gate may reference rows from the cameras
    table via ``hardware_config.camera_ids`` so one physical camera can serve
    several gates/booths. Inline entries (legacy) still win by label.
    """
    cams = gate.get_cameras()

    ids = gate.camera_ids if hasattr(gate, "camera_ids") else []
    if ids:
        from api.app.models import Camera

        rows = (
            await db.execute(select(Camera).where(Camera.id.in_(ids), Camera.is_active == True))  # noqa: E712
        ).scalars().all()
        by_id = {c.id: c for c in rows}
        seen = {(c.get("label") or "") for c in cams}
        for cam_id in ids:
            cam = by_id.get(cam_id)
            if cam is None:
                continue
            label = cam.name
            if label in seen:
                continue
            url = cam.rtsp_url or cam.snapshot_url
            if not url:
                continue
            cams.append(
                {
                    "url": url,
                    "preview_url": f"/api/cameras/{cam.id}/stream",
                    "snapshot_preview_url": f"/api/cameras/{cam.id}/snapshot",
                    "label": label,
                    "username": cam.username,
                    "password": cam.password,
                    "auth_type": cam.auth_type or "none",
                }
            )
            seen.add(label)
    return cams


async def enqueue_snapshots_for_gate(
    db: AsyncSession,
    gate_code: str,
    transaction_id: int,
    snapshot_type: str,
) -> None:
    """Enqueue snapshot jobs for all cameras on a gate.

    Args:
        db: Database session
        gate_code: Gate code (e.g., "GIN01", "GOUT01")
        transaction_id: Transaction to link snapshots to
        snapshot_type: "entry" or "exit"
    """
    try:
        from api.app.models import Gate
        from shared.redis import get_arq_redis

        result = await db.execute(select(Gate).where(Gate.code == gate_code))
        gate = result.scalar_one_or_none()
        if gate is None:
            return

        cameras = await resolve_gate_cameras(db, gate)
        if not cameras:
            return

        arq_redis = await get_arq_redis()
        for idx, cam in enumerate(cameras):
            cam_key = cam.get("label") or str(idx)
            await arq_redis.enqueue_job(
                "take_snapshot",
                gate_id=gate_code,
                camera_url=cam["url"],
                transaction_id=transaction_id,
                snapshot_type=snapshot_type,
                camera_label=cam.get("label"),
                camera_username=cam.get("username"),
                camera_password=cam.get("password"),
                camera_auth_type=cam.get("auth_type", "none"),
                _job_id=f"snapshot:{snapshot_type}:{transaction_id}:{cam_key}",
                _queue_name="arq:queue:critical",
            )

        logger.info(
            f"{snapshot_type}_snapshot_enqueued",
            transaction_id=transaction_id,
            gate_id=gate_code,
            count=len(cameras),
        )
    except Exception as exc:
        logger.warning(
            f"{snapshot_type}_snapshot_enqueue_failed",
            transaction_id=transaction_id,
            gate_id=gate_code,
            error=str(exc),
        )
